"""The 1.4 API test suites (molior-testing tests/api-tests/*.yml, run with pyresttest) translated to Python.

One function per yml file, same file name. Each step keeps the name of the yml test, its request and its checks.
Changed: the git URLs point to the public test repos (github.com/molior-dbs/test-*) instead of the internal git server,
the base mirror is trixie/13 instead of stretch/9.3 (also in the checks: 9.3 is 13). Expected status: as in the yml,
pyresttest's default (200 to 299) where the yml has none. A yml `delay` in front of a step that waits for an async
aptly operation becomes polling (poll(): every 2 s, at most 120 s).
"""
import time

import requests

from utils import logger

GIT = "https://github.com/molior-dbs/{}.git"


class Step:
    """One pyresttest test: a request and its checks."""

    def __init__(self, v, url_key="molior_url"):
        self.v = v
        self.base = v[url_key]
        self.session = requests.Session()

    def __call__(self, name, method, url, json=None, expected_status=None):
        logger.warning("api test step: %s", name)
        r = self.session.request(method, self.base + url, json=json, timeout=60)
        if expected_status:
            assert r.status_code in expected_status, "{}: {} {}".format(name, r.status_code, r.text)
        else:
            assert 200 <= r.status_code < 300, "{}: {} {}".format(name, r.status_code, r.text)
        return r


def init_testproject(v):
    step = Step(v)
    project, version = v["project_name"], v["projectversion_name"]
    step("Login", "POST", "/api/login", {"username": v["api_user"], "password": v["api_password"]},
         expected_status=[200])
    step("Create Project", "POST", "/api/projects", {"name": project})
    step("Create Projectversion", "POST", "/api2/projectbase/{}/versions".format(project),
         {"basemirror": "trixie/13", "architectures": ["amd64"], "name": version, "description": "validation test",
          "dependency_policy": "strict", "cibuilds": False})
    data = step("Get Projectversion", "GET", "/api2/project/{}/{}".format(project, version)).json()
    assert data["name"] == version
    assert data["project_name"] == project

    repos = "/api2/project/{}/{}/repositories".format(project, version)
    for name, repo in (("Track", "test-track"), ("Tick", "test-tick"), ("Trick", "test-trick"),
                       ("BadTrick", "test-badtrick"), ("BadTrack", "test-badtrack"), ("Test", "test-project"),
                       ("Ci-Build", "test-ci-build")):
        step("Add Sourcerepository " + name, "POST", repos, {"architectures": ["amd64"], "url": GIT.format(repo)})

    step("Enable Ci-Builds on Projectversion", "PUT", "/api2/project/{}/{}".format(project, version),
         {"description": "validation tests with ci", "dependency_policy": "strict", "cibuilds": True},
         expected_status=[200])
    step("Create Sourcerepository Build-Notifications", "POST", repos,
         {"architectures": ["amd64"], "url": GIT.format("test-build-notifications")})


def get_tests(v):
    step = Step(v)
    step("Login", "POST", "/api/login", {"username": v["api_user"], "password": v["api_password"]},
         expected_status=[200])
    r = step("Get Basemirrors", "GET", "/api/projectversions?isbasemirror=true")
    assert "json" in r.headers.get("content-type", "")
    data = r.json()
    assert data["total_result_count"] > 0
    assert [pv["id"] for pv in data["results"] if pv["name"] == "13"]


def aptly(v):
    """aptly auth tests: run against the aptly API URL"""
    step = Step(v, "aptly_api_url")
    step("Authentication", "POST", "/", expected_status=[401])


def poll(step, name, method, url, json=None, expected_status=None, timeout=120, interval=2):
    """A step that is repeated (every 2 s, at most 120 s) until it gets the expected status: replaces the yml 'delay'
    in front of steps that wait for an async operation (aptly publish/drop). Fails with the last response."""
    start = time.time()
    while True:
        try:
            return step(name, method, url, json, expected_status)
        except AssertionError:
            if time.time() - start >= timeout:
                raise
            logger.warning("api test step: %s: not yet, retrying in %ss", name, interval)
            time.sleep(interval)


def delete_projectversion(v):
    step, aptly = Step(v), Step(v, "aptly_url")
    project = v["project_name"]
    step("Login", "POST", "/api/login", {"username": v["api_user"], "password": v["api_password"]},
         expected_status=[200])
    step("Create Projectversion", "POST", "/api2/projectbase/{}/versions".format(project),
         {"basemirror": "trixie/13", "architectures": ["amd64"], "name": "to-delete", "description": "validation test",
          "dependency_policy": "strict", "cibuilds": False})
    poll(aptly, "Creation of ProjectVersion on aptly", "GET",
         "/trixie/13/repos/{}/to-delete/dists/stable/Release".format(project), expected_status=[200])
    step("Create an overlay (to block deletion)", "POST", "/api2/project/{}/to-delete/overlay".format(project),
         {"name": "blocking-overlay"})
    step("Delete the ProjectVersion", "DELETE", "/api2/project/{}/to-delete".format(project), expected_status=[400])
    step("Delete the Blocking overlay", "DELETE", "/api2/project/{}/blocking-overlay".format(project))
    poll(step, "Delete the ProjectVersion for good", "DELETE", "/api2/project/{}/to-delete".format(project))
    poll(aptly, "Test deletion of ProjectVersion on aptly", "GET",
         "/trixie/13/repos/{}/to-delete/dists/stable/".format(project), expected_status=[404])


def clone_projectversion(v):
    step, aptly = Step(v), Step(v, "aptly_url")
    project, version = v["project_name"], v["projectversion_name"]
    step("Login", "POST", "/api/login", {"username": v["api_user"], "password": v["api_password"]},
         expected_status=[200])
    # 1.4 extracted id and name of the clone (never used); the 1.5 copy returns {"build_id", "rebuild_ids"}
    step("Clone ProjectVersion", "POST", "/api2/project/{}/{}/copy".format(project, version),
         {"basemirror": "trixie/13", "architectures": ["amd64"], "name": "cloned-version",
          "description": "cloned projectversion", "dependency_policy": "strict", "cibuilds": True})
    original = step("Get the original projectversion for comparision", "GET",
                    "/api2/project/{}/{}".format(project, version)).json()
    data = step("Compare original projecversion with clone", "GET",
                "/api2/project/{}/cloned-version".format(project)).json()
    for key in ("basemirror", "ci_builds_enabled", "dependency_policy"):
        assert str(data[key]) == str(original[key]), "{}: {} != {}".format(key, data[key], original[key])
    total_repos = step("Get all repos from the original projectversion for comparision", "GET",
                       "/api2/project/{}/{}/repositories".format(project, version)).json()["total_result_count"]
    data = step("Compare repos to original projectversion for comparision", "GET",
                "/api2/project/{}/cloned-version/repositories".format(project)).json()
    assert str(data["total_result_count"]) == str(total_repos)
    poll(aptly, "Creation of ProjectVersion clone on aptly", "GET",
         "/trixie/13/repos/{}/cloned-version/dists/stable/Release".format(project), expected_status=[200])


def overlay_projectversion(v):
    step, aptly = Step(v), Step(v, "aptly_url")
    project, version = v["project_name"], v["projectversion_name"]
    step("Login", "POST", "/api/login", {"username": v["api_user"], "password": v["api_password"]},
         expected_status=[200])
    step("Create Overlay ProjectVersion", "POST", "/api2/project/{}/{}/overlay".format(project, version),
         {"name": "overlay-version"})
    basemirror = step("Get the original projectversion for comparision", "GET",
                      "/api2/project/{}/{}".format(project, version)).json()["basemirror"]
    data = step("Compare original projecversion with overlay", "GET",
                "/api2/project/{}/overlay-version".format(project)).json()
    assert str(data["basemirror"]) == str(basemirror)
    poll(aptly, "Creation of ProjectVersion overlay on aptly", "GET",
         "/trixie/13/repos/{}/overlay-version/dists/stable/Release".format(project), expected_status=[200])


def edit_dependencies(v):
    step = Step(v)
    project, version = v["project_name"], v["projectversion_name"]
    step("Login", "POST", "/api/login", {"username": v["api_user"], "password": v["api_password"]},
         expected_status=[200])
    step("Clone ProjectVersion", "POST", "/api2/project/{}/{}/copy".format(project, version),
         {"basemirror": "trixie/13", "architectures": ["amd64"], "name": "to-depend-on",
          "description": "dependable projectversion", "dependency_policy": "strict", "cibuilds": True})
    step("Add the dependency", "POST", "/api2/project/{}/{}/dependencies".format(project, version),
         {"dependency": "{}/to-depend-on".format(project), "use_cibuilds": False})
    data = step("Check if the dependency has been added", "GET",
                "/api2/project/{}/{}/dependencies".format(project, version)).json()
    assert data["results"][0]["project_name"] == project
    assert data["results"][0]["name"] == "to-depend-on"
    step("Delete the dependency", "DELETE",
         "/api2/project/{}/{}/dependency/{}/to-depend-on".format(project, version, project))
    data = step("Check if the dependency has been deleted", "GET",
                "/api2/project/{}/{}/dependencies".format(project, version)).json()
    assert data["total_result_count"] == 0


def sorted_projectversions(v):
    """sorted.yml: only the login, its sort check is commented out in the yml (as in 1.4)"""
    step = Step(v)
    step("Login", "POST", "/api/login", {"username": v["api_user"], "password": v["api_password"]},
         expected_status=[200])


def delete_repository(v):
    step = Step(v)
    project = v["project_name"]
    repos = "/api2/project/{}/repo-test-version/repositories".format(project)
    step("Login", "POST", "/api/login", {"username": v["api_user"], "password": v["api_password"]},
         expected_status=[200])
    step("Create Projectversion", "POST", "/api2/projectbase/{}/versions".format(project),
         {"basemirror": "trixie/13", "architectures": ["amd64"], "name": "repo-test-version",
          "description": "validation test", "dependency_policy": "strict", "cibuilds": False})
    step("Add the repository to the projectversion", "POST", repos,
         {"url": GIT.format("test-tick"), "architectures": ["amd64"]})
    data = step("Verify that the repository has been added", "GET", repos).json()
    assert data["total_result_count"] == 1
    sourcerepo_id = data["results"][0]["id"]
    step("Remove the repository from the projectversion", "DELETE",
         "/api2/project/{}/repo-test-version/repository/{}".format(project, sourcerepo_id))
    data = step("Verify that the repository has been removed", "GET", repos).json()
    assert data["total_result_count"] == 0


SUITES = {
    "tests/api-tests/init-testproject.yml": init_testproject,
    "tests/api-tests/get-tests.yml": get_tests,
    "tests/api-tests/aptly.yml": aptly,
    "tests/api-tests/delete-projectversion.yml": delete_projectversion,
    "tests/api-tests/clone-projectversion.yml": clone_projectversion,
    "tests/api-tests/overlay-projectversion.yml": overlay_projectversion,
    "tests/api-tests/edit-dependencies.yml": edit_dependencies,
    "tests/api-tests/sorted.yml": sorted_projectversions,
    "tests/api-tests/delete-repository.yml": delete_repository,
}
