"""The 1.4 API test suites (molior-testing tests/api-tests/*.yml, run with pyresttest) translated to Python.

One function per yml file, same file name. Each step keeps the name of the yml test, its request and its checks.
Changed: the git URLs point to the public test repos (github.com/molior-dbs/test-*) instead of the internal git server,
the base mirror is trixie/13 instead of stretch/9.3. Expected status: as in the yml, pyresttest's default (200 to 299)
where the yml has none.
"""
import requests

from utils import logger

GIT = "https://github.com/molior-dbs/{}.git"


class Step:
    """One pyresttest test: a request and its checks."""

    def __init__(self, v):
        self.v = v
        self.session = requests.Session()

    def __call__(self, name, method, url, json=None, expected_status=None):
        logger.warning("api test step: %s", name)
        r = self.session.request(method, self.v["molior_url"] + url, json=json, timeout=60)
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


SUITES = {
    "tests/api-tests/init-testproject.yml": init_testproject,
}
