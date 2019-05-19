"""
Provides test molior core class.
"""
from molior.aptly import AptlyApi


def test_check_status_code_succ():
    """
    Test check status code success
    """
    api = AptlyApi("http://foo.bar/api", "a@b.c", username="foo", password="bar")
    res = api._AptlyApi__check_status_code(200)
    assert res


def test_check_status_code_fail():
    """
    Test check status code fail
    """
    api = AptlyApi("http://foo.bar/api", "a@b.c", username="foo", password="bar")
    res1 = api._AptlyApi__check_status_code(400)
    res2 = api._AptlyApi__check_status_code(401)
    res3 = api._AptlyApi__check_status_code(403)
    res4 = api._AptlyApi__check_status_code(404)
    res5 = api._AptlyApi__check_status_code(502)
    res6 = api._AptlyApi__check_status_code(500)

    assert not res1
    assert not res2
    assert not res3
    assert not res4
    assert not res5
    assert not res6


def test_get_aptly_names_repo():
    """
    Test check get aptly names repo
    """
    base_mirror = "jessie"
    base_mirror_version = "8.10"
    repo = "molior"
    version = "1.2.0"
    is_mirror = False
    name, publish_name = AptlyApi.get_aptly_names(base_mirror, base_mirror_version, repo, version, is_mirror)

    assert name == "jessie-8.10-molior-1.2.0"
    assert publish_name == "jessie_8.10_repos_molior_1.2.0"


def test_get_aptly_names_mirror():
    """
    Test check get aptly names mirror
    """
    base_mirror = "jessie"
    base_mirror_version = "8.10"
    repo = "nodejs"
    version = "7.0"
    is_mirror = True
    name, publish_name = AptlyApi.get_aptly_names(base_mirror, base_mirror_version, repo, version, is_mirror)

    assert name == "jessie-8.10-nodejs-7.0"
    assert publish_name == "jessie_8.10_mirrors_nodejs_7.0"


def test_get_aptly_names_basemirror():
    """
    Test check get aptly names base mirror
    """
    base_mirror = None
    base_mirror_version = None
    repo = "jessie"
    version = "8.10"
    is_mirror = True
    name, publish_name = AptlyApi.get_aptly_names(base_mirror, base_mirror_version, repo, version, is_mirror)

    assert name == "jessie-8.10"
    assert publish_name == "jessie_8.10"
