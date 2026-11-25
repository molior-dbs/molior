"""parse_git_url (molior/giturl.py). The expected values are what giturlparse returned for these URLs, except the
two marked cases where giturlparse was wrong."""
import pytest

from molior.giturl import parse_git_url, GitUrlError


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/molior-dbs/test-submodule.git", ("github.com", "molior-dbs", "test-submodule")),
    ("https://github.com/molior-dbs/test-submodule", ("github.com", "molior-dbs", "test-submodule")),
    ("https://github.com/molior-dbs/test-submodule/", ("github.com", "molior-dbs", "test-submodule")),
    ("git@github.com:molior-dbs/molior.git", ("github.com", "molior-dbs", "molior")),
    # giturlparse: ("molior-dbs", None, "molior")
    ("git@github.com:molior-dbs/molior", ("github.com", "molior-dbs", "molior")),
    ("ssh://git@example.com:7999/proj/repo.git", ("example.com", "proj", "repo")),
    ("ssh://git@example.com/group/sub/repo.git", ("example.com", "group/sub", "repo")),
    ("http://example.com/repo.git", ("example.com", None, "repo")),
    ("git://example.com/owner/repo.git", ("example.com", "owner", "repo")),
    ("https://user:secret@example.com/owner/repo.git", ("example.com", "owner", "repo")),
    ("https://example.com/scm/proj/my.repo.git", ("example.com", "scm/proj", "my.repo")),
    ("https://example.com/owner/repo.name", ("example.com", "owner", "repo.name")),
    ("http://127.0.0.1:8080/owner/repo.git", ("127.0.0.1", "owner", "repo")),
    ("example.com:owner/repo.git", ("example.com", "owner", "repo")),
])
def test_parse(url, expected):
    assert tuple(parse_git_url(url)) == expected


@pytest.mark.parametrize("url", [
    "not a url",
    "",
    None,
    "http://",
    # giturlparse: ("example.co", None, "m")
    "https://example.com/",
    "/srv/git/owner/repo.git",
])
def test_invalid(url):
    with pytest.raises(GitUrlError):
        parse_git_url(url)


def test_error_is_a_value_error():
    with pytest.raises(ValueError):
        parse_git_url("not a url")
