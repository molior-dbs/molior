"""
Tests for the body of POST /api/build (molior/fastapi/routers/v1/build.py): molior 1.4 accepted
force_ci and forceCI, clients may still send either.
"""
import pytest

# fastapi is in the molior image (molior:dev), not in molior-base:dev
pytest.importorskip("fastapi")
from molior.fastapi.routers.v1.build import TriggerBuildBody  # noqa: E402

REPO = "https://git.example.com/group/repo.git"


@pytest.mark.parametrize("body,expected", [
    ({"repository": REPO}, False),
    ({"repository": REPO, "force_ci": True}, True),
    ({"repository": REPO, "forceCI": True}, True),
    ({"repository": REPO, "forceCI": False}, False),
])
def test_force_ci(body, expected):
    assert TriggerBuildBody(**body).force_ci is expected
