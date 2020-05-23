from molior.model.sourcerepository import SourceRepository


def test_parse_repository_name():
    """
    Test parse_repository_name
    """
    s = SourceRepository
    s.url = "ssh://git@foo.com:1337/~jon/foobar.git"
    result = s.name
    assert result == "foobar"


def test_parse_repo_name_non_std():
    """
    Test parse_repository_name if an invalid repo url is passed
    """
    s = SourceRepository
    s.url = "ssh://user@server.com:1337/~jon/foobar"
    result = s.name
    assert result == "foobar"
