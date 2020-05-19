from molior.tools import parse_repository_name


def test_parse_repository_name():
    """
    Test parse_repository_name
    """
    url = "ssh://git@foo.com:1337/~jon/foobar.git"
    result = parse_repository_name(url)
    assert result == "foobar"


def test_parse_repo_name_non_std():
    """
    Test parse_repository_name if an invalid repo url is passed
    """
    url = "ssh://user@server.com:1337/~jon/foobar"
    result = parse_repository_name(url)
    assert result == "foobar"
