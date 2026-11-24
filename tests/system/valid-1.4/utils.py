"""Helpers of the 1.4 validation tests (molior-testing tests/utils.py), ported to the current API (/api2, the same
calls as the web UI). Same names and arguments as in 1.4; failures raise instead of returning 1."""
import json
import logging
import os
import time

import requests

MOLIOR_URL = os.environ.get("MOLIOR_URL", "http://web:8000").rstrip("/")
RESULTS = os.environ.get("RESULTS_DIR", "/tmp/results")
MIRROR_TIMEOUT = int(os.environ.get("MIRROR_TIMEOUT", "1500"))
BUILD_TIMEOUT = int(os.environ.get("BUILD_TIMEOUT", "1200"))
APTLY_URL = os.environ.get("APTLY_URL", "http://aptly:8000").rstrip("/")
ADMIN_PASSWORD = os.environ.get("MOLIOR_ADMIN_PASSWORD", "")
FINAL_STATES = ("successful", "build_failed", "publish_failed", "already_exists", "nothing_done")

logger = logging.getLogger("molior-validation")


def molior_session(molior_host=MOLIOR_URL):
    session = requests.Session()
    r = session.post(molior_host + "/api/login",
                     json={"username": "admin", "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return session


def create_mirror(
    molior_host,
    mirror_url,
    mirror_name,
    mirror_version,
    mirror_dist,
    components,
    architectures,
    is_basemirror=False,
    basemirror_id=None,
    keyurl=None,
    keyserver=None,
    keys=None,
    allow_rerun=False,
    mirror_filter="",
    filter_with_deps=False,
):
    """Creates a mirror and waits until it is ready and its Release file is served. For a base mirror also waits
    until the build environments (chroot builds) are done and checks that they were successful. Writes the
    timings to RESULTS_DIR/mirror-<name>-<version>.json."""
    assert basemirror_id is None, "basemirror_id: not ported yet (needed by test_mirror)"
    session = molior_session(molior_host)
    payload = {
        "mirrorname": mirror_name,
        "mirrorversion": mirror_version,
        "mirrortype": "1" if is_basemirror else "2",
        "mirrorurl": mirror_url,
        "mirrordist": mirror_dist,
        "mirrorcomponents": components,
        "architectures": architectures.split(","),
        "mirrorfilter": mirror_filter,
        "mirrorfilterwithdeps": filter_with_deps,
    }
    if keyurl:
        payload["mirrorkeyurl"] = keyurl
    if keyserver and keys:
        payload["mirrorkeyserver"] = keyserver
        payload["mirrorkeyids"] = keys

    start = time.time()
    res = session.post(molior_host + "/api2/mirror", json=payload, timeout=60)
    if res.status_code != 200:
        if "already exists" in res.text and allow_rerun:
            print("Mirror '{}-{}' exists".format(mirror_name, mirror_version))
            return 0
        raise AssertionError("Mirror '{}-{}' creation failed: {} {}".format(
            mirror_name, mirror_version, res.status_code, res.text))
    build_id = res.json()["build_id"]

    summary = {"mirror": "{}/{}".format(mirror_name, mirror_version), "build_id": build_id, "filter": mirror_filter,
               "filter_with_deps": filter_with_deps, "architectures": architectures}
    states = {}
    mirror = {}
    while True:
        assert time.time() - start < MIRROR_TIMEOUT, "timeout, last state {}".format(mirror.get("state"))
        mirror = session.get("{}/api2/mirror/{}/{}".format(molior_host, mirror_name, mirror_version), timeout=30).json()
        state = mirror.get("state")
        if state not in states:
            states[state] = round(time.time() - start)
            logger.warning("mirror %s/%s: %s after %ss", mirror_name, mirror_version, state, states[state])
        if state in ("error", "init_error"):
            break
        build = session.get("{}/api2/build/{}".format(molior_host, build_id), timeout=30).json()
        if state == "ready" and (not is_basemirror or build["buildstate"] in FINAL_STATES):
            break
        # stop on a failure, also if the mirror state is not updated (older molior versions, see buildenv.py)
        if build["buildstate"] in ("build_failed", "publish_failed"):
            break
        children = [session.get("{}/api2/build/{}".format(molior_host, c["id"]), timeout=30).json()
                    for c in build.get("children", [])]
        if any(c["buildstate"] in ("build_failed", "publish_failed") for c in children):
            break
        time.sleep(10)
    summary["seconds"] = round(time.time() - start)
    summary["states"] = states

    build = session.get("{}/api2/build/{}".format(molior_host, build_id), timeout=30).json()
    summary["buildstate"] = build["buildstate"]
    summary["chroots"] = []
    for child in build.get("children", []):
        c = session.get("{}/api2/build/{}".format(molior_host, child["id"]), timeout=30).json()
        keys = ("id", "buildtype", "architecture", "buildstate", "startstamp", "endstamp")
        summary["chroots"].append({k: c.get(k) for k in keys})
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "mirror-{}-{}.json".format(mirror_name, mirror_version)), "w") as f:
        json.dump(summary, f, indent=2)

    assert mirror.get("state") == "ready", "Mirror '{}-{}' creation failed: {}".format(
        mirror_name, mirror_version, json.dumps(summary))
    if is_basemirror:
        assert summary["chroots"], "no build environments created"
        failed = [c for c in summary["chroots"] if c["buildstate"] != "successful"]
        assert not failed, "build environments failed: {}".format(failed)
        assert build["buildstate"] == "successful", json.dumps(summary)

    release_url = "{}/dists/{}/Release".format(mirror.get("apt_url"), mirror_dist)
    res = requests.get(release_url, timeout=30)
    assert res.status_code == 200, "{} {}".format(release_url, res.status_code)
    print(release_url, "exists")
    print("Mirror '{}-{}' succesfully created".format(mirror_name, mirror_version))
    return 0


def wait_for_paralell_builds(molior_host, builds):
    """
    Waits until the deb builds of the given source packages are done (successful, build_failed or nothing_done),
    at most BUILD_TIMEOUT seconds (1.4: 60 times 10 s). Returns the deb builds found.
    """
    our_builds = []
    session = molior_session(molior_host)
    for _ in range(int(BUILD_TIMEOUT / 10)):
        time.sleep(10)

        builds_response = session.get("{}/api/builds".format(molior_host), params={"page": 1, "page_size": 100},
                                      timeout=30)
        assert builds_response.ok, "Could not get the builds"
        current_builds = builds_response.json().get("results")
        our_builds = [
            build for build in current_builds if build.get("sourcename") in builds and build.get("buildtype") == "deb"
        ]
        if not our_builds:
            continue
        done = True
        for sourcename in builds:
            found = False
            for b in our_builds:
                if b.get("sourcename") == sourcename:
                    found = True
                    if b.get("buildstate") not in ("successful", "build_failed", "nothing_done"):
                        done = False
                        break
            if not found:
                done = False
                break
            if not done:
                break
        if done:
            break

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "builds-{}.json".format(int(time.time()))), "w") as f:
        json.dump(current_builds, f, indent=2)
    return our_builds
