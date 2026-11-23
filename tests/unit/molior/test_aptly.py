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


def test_repo_create_returns_task_id():
    """
    Test repo_create returns the id of the aptly task, so that the caller can wait for it
    """
    import asyncio
    from molior.aptly.api import AptlyApi

    async def post(path, data=None):
        assert path == "/repos" and data == {"Name": "repo-1"}
        return {"ID": 7, "Name": "Create repository repo-1"}

    api = AptlyApi("http://aptly:3143", "gpg@key", username="user", password="pass")
    api.POST = post
    assert asyncio.run(api.repo_create("repo-1")) == 7


def _mirror_api():
    from molior.aptly.api import AptlyApi

    calls = []

    async def post(path, data=None):
        calls.append(("POST", path, data))
        return {"ID": 1}

    async def delete(path, data=None):
        calls.append(("DELETE", path, data))
        return {"ID": 2}

    async def wait_task(task_id):
        return True

    api = AptlyApi("http://aptly:3143", "gpg@key", username="user", password="pass")
    api.POST = post
    api.DELETE = delete
    api.wait_task = wait_task
    return api, calls


def test_mirror_publish_slash_workaround():
    """
    Test mirror_publish: '/' in the distribution is published as '_-' only with the workaround (old mirrors)
    """
    import asyncio

    for workaround, dist in ((True, "bookworm_-current"), (False, "bookworm/current")):
        api, calls = _mirror_api()
        asyncio.run(api.mirror_publish("bookworm", "12.8", "mcp", "1", "bookworm/current", ["non-free"],
                                       ["amd64"], workaround))
        assert calls[0][1] == "/publish/bookworm_12.8_mirrors_mcp_1"
        assert calls[0][2]["Distribution"] == dist
        assert calls[0][2]["Sources"] == [{"Component": "non-free", "Name": "bookworm-12.8-mcp-1-non-free"}]


def test_mirror_publish_flat_without_components():
    """
    Test mirror_publish of a flat mirror without components uses the mirror name
    """
    import asyncio

    api, calls = _mirror_api()
    asyncio.run(api.mirror_publish("bookworm", "12.8", "kube", "1", "./", [], ["amd64"]))
    assert calls[0][2]["Distribution"] == "./"
    assert calls[0][2]["Sources"] == [{"Name": "bookworm-12.8-kube-1"}]


def test_mirror_delete_publish_url():
    """
    Test mirror_delete: in the url aptly takes '_' as '/' and '__' as '_', the old format is published with '_-'
    """
    import asyncio

    expected = (
        (True, "bookworm/current", "bookworm__-current"),
        (True, "./", ".__-"),
        (True, "bookworm-security/updates", "bookworm-security__-updates"),
        (False, "bookworm/current", "bookworm_current"),
        (False, "./", "._"),
        (False, "bookworm", "bookworm"),
    )
    for workaround, dist, url in expected:
        api, calls = _mirror_api()
        asyncio.run(api.mirror_delete("bookworm", "12.8", "mcp", "1", dist, [], workaround))
        assert calls[0] == ("DELETE", "/publish/bookworm_12.8_mirrors_mcp_1/" + url, None)


def test_mirror_create_filter_with_deps():
    """
    Test mirror_create passes FilterWithDeps to aptly only together with a filter
    """
    import asyncio

    cases = (
        # filter, filter_with_deps, expected FilterWithDeps
        ("Priority (required) | debhelper", True, True),
        ("Priority (required) | debhelper", False, False),
        ("", True, False),
        (None, True, False),
    )
    for mirror_filter, with_deps, expected in cases:
        api, calls = _mirror_api()
        asyncio.run(api.mirror_create("trixie", "13.8", "", "", "http://deb.debian.org/debian", "trixie",
                                      ["main"], ["amd64"], mirror_filter, filter_with_deps=with_deps))
        assert calls[0][1] == "/mirrors"
        assert calls[0][2]["Filter"] == mirror_filter
        assert calls[0][2]["FilterWithDeps"] is expected


def test_mirror_create_filter_with_deps_default_off():
    """
    Test mirror_create keeps FilterWithDeps off by default (existing callers, existing mirrors)
    """
    import asyncio

    api, calls = _mirror_api()
    asyncio.run(api.mirror_create("trixie", "13.8", "", "", "http://deb.debian.org/debian", "trixie",
                                  ["main", "contrib"], ["amd64"], "Name (% python3*)"))
    assert [c[2]["Name"] for c in calls] == ["trixie-13.8-main", "trixie-13.8-contrib"]
    assert all(c[2]["FilterWithDeps"] is False for c in calls)
