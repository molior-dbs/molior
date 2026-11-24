"""Helpers of the 1.4 validation tests (molior-testing tests/utils.py), ported to the current API (/api2, the same
calls as the web UI). Same names and arguments as in 1.4; failures raise instead of returning 1."""
import json
import logging
import os
import subprocess
import time

import requests

MOLIOR_URL = os.environ.get("MOLIOR_URL", "http://web:8000").rstrip("/")
RESULTS = os.environ.get("RESULTS_DIR", "/tmp/results")
MIRROR_TIMEOUT = int(os.environ.get("MIRROR_TIMEOUT", "1500"))
BUILD_TIMEOUT = int(os.environ.get("BUILD_TIMEOUT", "1200"))
APTLY_URL = os.environ.get("APTLY_URL", "http://aptly:8000").rstrip("/")
APTLY_API_URL = os.environ.get("APTLY_API_URL", "http://aptly:3143").rstrip("/")
ADMIN_PASSWORD = os.environ.get("MOLIOR_ADMIN_PASSWORD", "")
MOLIOR_NAMESPACE = os.environ.get("MOLIOR_NAMESPACE", "molior")
MOLIOR_DEPLOYMENT = os.environ.get("MOLIOR_DEPLOYMENT", "molior")
MOLIOR_CONTAINER = os.environ.get("MOLIOR_CONTAINER", "molior-server")
BUILDOUT = "/var/lib/molior/buildout"
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
    if basemirror_id:
        # POST /api2/mirror takes the base mirror as "name/version", 1.4 took its id
        payload["basemirror"] = basemirror_name(session, molior_host, basemirror_id)
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


def get_basemirror(molior_host, mirror_name, mirror_version):
    """
    Returns the id of the base mirror (1.4: the same, from the list of all mirrors).
    """
    session = molior_session(molior_host)
    res = session.get("{}/api2/mirror/{}/{}".format(molior_host, mirror_name, mirror_version), timeout=30)
    assert res.status_code == 200, "Cannot find base mirror: {} {}".format(res.status_code, res.text)
    mirror = res.json()
    assert mirror.get("is_basemirror"), "{}/{} is not a base mirror".format(mirror_name, mirror_version)
    return mirror.get("id")


def basemirror_name(session, molior_host, basemirror_id):
    """
    Returns "name/version" of the base mirror with the given id, as POST /api2/mirror expects it.
    """
    res = session.get("{}/api/mirrors".format(molior_host), params={"is_basemirror": "true", "page_size": 100},
                      timeout=30)
    assert res.ok, "Could not get the mirrors: {} {}".format(res.status_code, res.text)
    for mirror in res.json().get("results"):
        if mirror.get("id") == basemirror_id:
            return "{}/{}".format(mirror.get("name"), mirror.get("version"))
    raise AssertionError("base mirror {} not found".format(basemirror_id))


def molior_exec(command, timeout=60):
    """
    Runs a shell command in the molior server container and returns its stdout (replaces the 1.4 ssh_run).
    Raises when the command fails (1.4: check=True), with its stderr in the message.

    Example:

        >>> molior_exec("ls -al /var/lib/molior")
    """
    result = subprocess.run(
        ["kubectl", "-n", MOLIOR_NAMESPACE, "exec", "deploy/" + MOLIOR_DEPLOYMENT, "-c", MOLIOR_CONTAINER,
         "--", "sh", "-c", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    assert result.returncode == 0, "molior_exec '{}' failed ({}): {}".format(
        command, result.returncode, result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout.decode("utf-8", errors="replace")


def get_build_log(build_id, marker=None, timeout=60):
    """
    Returns the build log of a build, read from the molior server (1.4: GET /buildout/<id>/build.log, which 1.5
    does not serve). With a marker, waits until the log contains it, at most timeout seconds: the server writes
    the log through a queue, so the end of the log can be written after the build state has changed.
    Returns the last log read (the caller checks the marker).
    """
    deadline = time.time() + timeout
    while True:
        log = molior_exec("cat {}/{}/build.log".format(BUILDOUT, int(build_id)))
        if not marker or marker in log or time.time() > deadline:
            return log
        time.sleep(2)


def get_deb_build_ids(molior_host, sourcenames):
    """
    Ids of the existing deb builds of the given source packages. A test that builds a source again passes them to
    the ignore_ids argument of wait_for_paralell_builds, so that it waits for the new builds only.
    """
    session = molior_session(molior_host)
    ids = set()
    for name in sourcenames:
        response = session.get("{}/api/builds".format(molior_host),
                               params={"search": name, "page": 1, "page_size": 100}, timeout=30)
        assert response.ok, "Could not get the builds"
        ids |= {b["id"] for b in response.json().get("results")
                if b.get("sourcename") == name and b.get("buildtype") == "deb"}
    return ids


def wait_for_paralell_builds(molior_host, builds, ignore_ids=()):
    """
    Waits until the deb builds of the given source packages are done (successful, build_failed or nothing_done),
    at most BUILD_TIMEOUT seconds (1.4: 60 times 10 s). Deb builds with an id in ignore_ids are not looked at
    (builds of an earlier test). Returns the deb builds found.
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
            and build.get("id") not in ignore_ids
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


def get_build(molior_host, name, buildtype="deb", buildstate=None, timeout=300):
    """
    Gets the build id

    Args:
        name (str): Name of the package

    Same as 1.4, except that the list is requested with search=name and page_size=100 (1.4 passed its params into
    str.format, so the API got no parameters and returned only the newest 10 builds).
    """
    build = None
    with molior_session(molior_host) as molior:
        for i in range(int(timeout/10)):
            response = molior.get("{}/api/builds".format(molior_host),
                                  params={"search": name, "page": 1, "page_size": 100}, timeout=30)
            assert response.ok, "Could not get builds from molior"

            results = response.json().get("results")
            for result in results:
                if result.get("buildtype") != buildtype:
                    continue
                if result.get("sourcename") != name:
                    continue
                if buildstate and result.get("buildstate") != buildstate:
                    continue
                build = result
                break
            if build:
                break
            time.sleep(10)

    assert build, "Could not determine the build id"
    return build
