"""
Build counts of the project and project version lists (molior/model/buildcounts.py, ProjectVersion.data).
Needs sqlalchemy: run inside the molior image, not on the host.
"""
from types import SimpleNamespace
from unittest.mock import patch

from molior.model import buildcounts
from molior.model.projectversion import ProjectVersion


class FakeDB:
    """Returns the given rows for every execute and records the calls."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, query, params):
        self.calls.append((str(query), params))
        return iter(self.rows)


def test_projectversion_counts_one_query_for_all_ids():
    db = FakeDB([(5, 3, 1), (7, 0, 2)])
    counts = buildcounts.projectversion_build_counts(db, [7, 5, 9, 5, None])
    assert counts == {5: (3, 1), 7: (0, 2), 9: (0, 0)}     # 9 has no builds
    assert len(db.calls) == 1
    query, params = db.calls[0]
    assert params == {"ids": [5, 7, 9]}                       # unique, sorted, no None
    assert "count(DISTINCT toplevel_id)" in query             # top level builds, not rows
    assert "buildtype IN ('deb', 'source')" in query
    assert "NOT is_deleted" in query


def test_project_counts_group_by_project():
    db = FakeDB([(1, 10, 4)])
    assert buildcounts.project_build_counts(db, [1, 2]) == {1: (10, 4), 2: (0, 0)}
    query, params = db.calls[0]
    assert "GROUP BY pv.project_id" in query
    assert "count(DISTINCT b.toplevel_id)" in query           # a build for two versions counts once


def test_no_ids_no_query():
    db = FakeDB([])
    assert buildcounts.projectversion_build_counts(db, []) == {}
    assert buildcounts.project_build_counts(db, [None]) == {}
    assert db.calls == []


def _pv(id, is_mirror=False):
    project = SimpleNamespace(name="p", is_mirror=is_mirror)
    return SimpleNamespace(
        id=id, name="v%d" % id, description="", project=project, mirror_architectures="{amd64}", is_locked=False,
        dependency_policy="strict", dependencies=[], dependents=[], projectversiontype="regular",
        ci_builds_enabled=False, retention_successful_builds=1, retention_failed_builds=7, publish_s3=False,
        s3_endpoint="", s3_path="", basemirror=None, mirror_state=None,
        get_apt_repo=lambda url_only=False: "apt",
    )


def _data(pv, counts=None):
    return ProjectVersion.data(pv, counts)


def test_data_uses_given_counts_without_query():
    with patch("molior.model.projectversion.projectversion_build_counts") as query:
        d = _data(_pv(3), (12, 4))
    query.assert_not_called()
    assert d["buildCount"] == 12 and d["cibuildCount"] == 4


def test_data_without_counts_queries_its_own():
    pv = _pv(3)
    with patch("molior.model.projectversion.object_session", return_value="db"), \
            patch("molior.model.projectversion.projectversion_build_counts", return_value={3: (2, 1)}) as query:
        d = _data(pv)
    query.assert_called_once_with("db", [3])
    assert d["buildCount"] == 2 and d["cibuildCount"] == 1


def test_data_mirror_has_no_counts_and_no_query():
    with patch("molior.model.projectversion.projectversion_build_counts") as query:
        d = _data(_pv(3, is_mirror=True))
    query.assert_not_called()
    assert "buildCount" not in d


def test_data_list_one_query_for_the_page():
    pvs = [_pv(1), _pv(2), _pv(3, is_mirror=True)]
    for pv in pvs:
        pv.data = lambda counts=None, pv=pv: ProjectVersion.data(pv, counts)
    with patch("molior.model.projectversion.projectversion_build_counts",
               return_value={1: (5, 0), 2: (0, 0)}) as query:
        result = ProjectVersion.data_list("db", pvs)
    query.assert_called_once_with("db", [1, 2])               # the mirror is not counted
    assert [r.get("buildCount") for r in result] == [5, 0, None]
