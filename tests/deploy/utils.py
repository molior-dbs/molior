"""Helpers of the deploy tests: the API calls that create the base mirror and the project, and the waits.
The tests run on the runner host (molior-deploy needs root, loop devices and docker), so the URLs are the ports
that tests/deploy/deploy-tests.sh maps from the test cluster to the host."""
import json
import logging
import os
import time

import requests

MOLIOR_URL = os.environ.get("MOLIOR_URL", "http://127.0.0.1:30080").rstrip("/")
APTLY_URL = os.environ.get("APTLY_URL", "http://127.0.0.1:30088").rstrip("/")
ADMIN_PASSWORD = os.environ.get("MOLIOR_ADMIN_PASSWORD", "")
RESULTS = os.environ.get("RESULTS_DIR", "/tmp/results")
MIRROR_TIMEOUT = int(os.environ.get("MIRROR_TIMEOUT", "3600"))
BUILD_TIMEOUT = int(os.environ.get("BUILD_TIMEOUT", "1800"))
# build states that do not change any more (molior/model/build.py BUILD_STATES)
FINAL_STATES = ("successful", "build_failed", "publish_failed", "already_exists", "already_failed", "nothing_done")

logger = logging.getLogger("molior-deploy-tests")


def molior_session():
    session = requests.Session()
    r = session.post(MOLIOR_URL + "/api/login", json={"username": "admin", "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return session


def save(name, data):
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, name), "w") as f:
        json.dump(data, f, indent=2)


def create_basemirror(name, version, url, dist, components, architectures, keyserver, keys, mirror_filter):
    """Creates a base mirror (filtered, with the dependencies of the filter) and waits until it and its build
    environments are done. Fails if one of them failed."""
    session = molior_session()
    payload = {
        "mirrorname": name,
        "mirrorversion": version,
        "mirrortype": "1",
        "mirrorurl": url,
        "mirrordist": dist,
        "mirrorcomponents": components,
        "architectures": architectures,
        "mirrorfilter": mirror_filter,
        "mirrorfilterwithdeps": True,
        "mirrorkeyserver": keyserver,
        "mirrorkeyids": keys,
    }
    start = time.time()
    res = session.post(MOLIOR_URL + "/api2/mirror", json=payload, timeout=60)
    assert res.status_code == 200, "mirror {}/{}: {} {}".format(name, version, res.status_code, res.text)
    build_id = res.json()["build_id"]

    states = {}
    mirror, build = {}, {}
    while time.time() - start < MIRROR_TIMEOUT:
        mirror = session.get("{}/api2/mirror/{}/{}".format(MOLIOR_URL, name, version), timeout=30).json()
        state = mirror.get("state")
        if state not in states:
            states[state] = round(time.time() - start)
            logger.warning("mirror %s/%s: %s after %ss", name, version, state, states[state])
        build = session.get("{}/api2/build/{}".format(MOLIOR_URL, build_id), timeout=30).json()
        if state in ("error", "init_error") or build["buildstate"] in FINAL_STATES:
            break
        children = [session.get("{}/api2/build/{}".format(MOLIOR_URL, c["id"]), timeout=30).json()
                    for c in build.get("children", [])]
        if any(c["buildstate"] in ("build_failed", "publish_failed") for c in children):
            break
        time.sleep(10)

    chroots = [session.get("{}/api2/build/{}".format(MOLIOR_URL, c["id"]), timeout=30).json()
               for c in build.get("children", [])]
    summary = {"mirror": "{}/{}".format(name, version), "build_id": build_id, "seconds": round(time.time() - start),
               "states": states, "buildstate": build.get("buildstate"),
               "chroots": [{k: c.get(k) for k in ("id", "architecture", "buildstate")} for c in chroots]}
    save("mirror-{}-{}.json".format(name, version), summary)
    assert mirror.get("state") == "ready", json.dumps(summary)
    assert build.get("buildstate") == "successful", json.dumps(summary)
    assert chroots and all(c["buildstate"] == "successful" for c in chroots), json.dumps(summary)


def create_project(project, version, basemirror, architectures, repo_url):
    """Creates the project, its projectversion and adds the source repository (molior builds it)."""
    session = molior_session()
    r = session.post(MOLIOR_URL + "/api/projects", json={"name": project}, timeout=30)
    assert r.ok, r.text
    r = session.post("{}/api2/projectbase/{}/versions".format(MOLIOR_URL, project),
                     json={"basemirror": basemirror, "architectures": architectures, "name": version,
                           "description": "deploy test", "dependency_policy": "strict", "cibuilds": False},
                     timeout=30)
    assert r.ok, r.text
    r = session.post("{}/api2/project/{}/{}/repositories".format(MOLIOR_URL, project, version),
                     json={"architectures": architectures, "url": repo_url}, timeout=30)
    assert r.ok, r.text


def wait_for_build(sourcename):
    """Waits until the source build and the deb builds of sourcename are done, fails if one is not successful."""
    session = molior_session()
    start = time.time()
    builds = []
    while time.time() - start < BUILD_TIMEOUT:
        r = session.get(MOLIOR_URL + "/api/builds", params={"search": sourcename, "page": 1, "page_size": 100},
                        timeout=30)
        assert r.ok, r.text
        builds = [b for b in r.json().get("results") if b.get("sourcename") == sourcename
                  and b.get("buildtype") in ("source", "deb")]
        source = [b for b in builds if b["buildtype"] == "source"]
        debs = [b for b in builds if b["buildtype"] == "deb"]
        if any(b["buildstate"] in FINAL_STATES and b["buildstate"] != "successful" for b in builds):
            break
        if source and debs and all(b["buildstate"] == "successful" for b in builds):
            break
        time.sleep(10)
    save("builds-{}.json".format(sourcename), builds)
    states = ["{} {} {}".format(b["id"], b["buildtype"], b["buildstate"]) for b in builds]
    assert builds and all(b["buildstate"] == "successful" for b in builds), \
        "builds of {} after {} s: {}".format(sourcename, round(time.time() - start), ", ".join(states) or "none")
