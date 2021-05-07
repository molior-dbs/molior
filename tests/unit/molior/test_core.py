import pytest
import asyncio

from pathlib import Path
from mock import patch, MagicMock

from molior.molior.core import get_projectversion, get_target_config
from molior.molior.core import get_maintainer, get_target_arch
from molior.tools import is_name_valid, validate_version_format


def test_get_projectversion_no_cfg():
    """
    Test get_projectversion if config dict is empty
    """
    path = Path("/foo/bar")
    with patch("molior.molior.core.logger"):
        result = get_projectversion(path)
        assert result == ""


def test_get_projectversion_v_set():
    """
    Test get_projectversion if a cfg version is set
    """
    with patch(
           "molior.molior.core.Configuration") as mock, patch(
           "molior.molior.core.logger"):

        cfg = MagicMock()
        cfg.config_version = "1"
        mock.return_value = cfg

        path = Path("/foo/bar")
        setattr(path.__class__, "exists", MagicMock(return_value=True))
        result = get_projectversion(path)
        assert result == ""


def test_get_projectversion_n_v_set():
    """
    Test get_projectversion if no cfg version is set but no target_repo_version
    """
    with patch(
           "molior.molior.core.Configuration") as mock, patch(
           "molior.molior.core.logger"):
        cfg = MagicMock()
        cfg.config_version = None
        cfg.target_repo_version = None
        mock.return_value = cfg

        path = Path("/foo/bar")
        setattr(path.__class__, "exists", MagicMock(return_value=True))
        result = get_projectversion(path)
        assert result == ""


def test_get_projectversion_tgt_inv():
    """
    Test get_projectversion if no cfg version is set and an invalid target_repo_version is set
    """
    with patch(
           "molior.molior.core.Configuration") as mock, patch(
           "molior.molior.core.logger"):
        cfg = MagicMock()
        cfg.config_version = None
        cfg.target_repo_version = 1
        mock.return_value = cfg

        path = Path("/foo/bar")
        setattr(path.__class__, "exists", MagicMock(return_value=True))
        result = get_projectversion(path)
        assert result == ""


def test_get_projectversion_tgt_set():
    """
    Test get_projectversion if no cfg version is set and a valid target_repo_version is set
    """
    with patch(
           "molior.molior.core.Configuration") as mock, patch(
           "molior.molior.core.logger"):
        cfg = MagicMock()
        cfg.config_version = None
        cfg.target_repo_version = "foo-next"
        mock.return_value = cfg

        path = Path("/foo/bar")
        setattr(path.__class__, "exists", MagicMock(return_value=True))
        result = get_projectversion(path)
        assert result == "foo-next"


def test_get_target_config_no_cfg():
    """
    Test get target config if config does not exist
    """
    path = Path("/foo/bar")
    setattr(path.__class__, "exists", MagicMock(return_value=False))
    with patch("molior.molior.core.logger"):
        result = get_target_config(path)
        assert result == []


def test_get_target_cfg_empty_cfg():
    """
    Test get target config if config is empty
    """
    with patch(
           "molior.molior.core.Configuration") as mock, patch(
           "molior.molior.core.logger"):
        cfg = MagicMock()
        cfg.config.return_value = {}
        mock.return_value = cfg

        path = Path("/foo/bar")
        setattr(path.__class__, "exists", MagicMock(return_value=True))
        result = get_target_config(path)
        assert result == []


def test_get_target_config():
    """
    Test get target config
    """
    with patch(
           "molior.molior.core.Configuration") as mock, patch(
           "molior.molior.core.logger"):
        cfg = MagicMock()
        cfg.config.return_value = {"targets": {"testproject": ["1", "next"]}}
        mock.return_value = cfg

        path = Path("/foo/bar")
        setattr(path.__class__, "exists", MagicMock(return_value=True))
        result = get_target_config(path)
        assert set(result).issubset([("testproject", "1"), ("testproject", "next")])


def test_get_maintainer():
    """
    Test get maintainer
    """
    path = "/foo/bar"
    with patch("molior.molior.core.get_changelog_attr",
               side_effect=asyncio.coroutine(lambda a, b: "Jon Doe <jon@doe.com>")) as get_changelog_attr:

        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(get_maintainer(path))
        get_changelog_attr.assert_called_with("Maintainer", path)
        assert res == ("Jon", "Doe", "jon@doe.com")


def test_get_maintainer_none():
    """
    Test get maintainer if empty
    """
    path = "/foo/bar"
    with patch("molior.molior.core.get_changelog_attr",
               side_effect=asyncio.coroutine(lambda a, b: "")):

        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(get_maintainer(path))
        assert res is None


def test_get_maintainer_invalid():
    """
    Test get maintainer if invalid
    """
    path = "/foo/bar"
    with patch("molior.molior.core.get_changelog_attr",
               side_effect=asyncio.coroutine(lambda a, b: "Jon Doe")):

        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(get_maintainer(path))
        assert res is None


def test_get_target_arch():
    """
    Test get target architecture
    """
    build = MagicMock()
    session = MagicMock()
    build.projectversion.mirror_architectures = "{armhf,i386}"
    build.buildtype = "build"
    ret = get_target_arch(build, session)
    assert ret == "i386"


@pytest.mark.parametrize(
    "test_input,expected",
    [
        ("1.0.0", True),
        ("1.0-alpha1", True),
        ("this-Is-a.version", True),
        ("1.0_alpha", False),
        ("3.5+devel5", False),
        ("99.12.33.43~inv", False),
        ("1 with space", False),
        ("4.99/1", False),
        ("version?", False),
        (" ", False),
        ("", False),
        ("_", False),
    ],
)
def test_is_name_valid(test_input, expected):
    """
    Tests the validity of a version/project name
    """
    assert is_name_valid(test_input) == expected


@pytest.mark.parametrize(
    "test_version_input,expected_validity",
    [
        ("", False),
        ("v", False),
        ("V", False),
        ("va", False),
        ("vx", False),
        ("v-alpha1", False),
        ("v+alpha1", False),
        ("v0", True),
        ("0", False),
        ("v1", True),
        ("v1.", False),
        ("V1", False),
        ("V1.", False),
        ("v1.0", True),
        ("V1.0", False),
        ("v1.0.0", True),
        ("v1.0.0.", False),
        ("v1.0.0.0", True),
        ("v1.0.0.0.", False),
        ("v1.0.0.0.0", True),
        ("1", False),
        ("v1..", False),
        ("v1.0..", False),
        ("1.", False),
        ("1..", False),
        ("1.0-alpha1", True),
        ("1.0~alpha1", True),
        ("1.0+alpha1", True),
        ("1.0@alpha1", False),
        ("1.0alpha1", True),
        ("1.0-alpha11one", True),
        ("v1.0-alpha1", True),
        ("v1.0~alpha1", True),
        ("v1.0+alpha1", True),
        ("v1.0-alpha11one", True),
        ("1.0-", False),
        ("this-Is-a.version", False),
        ("1.0_alpha", False),
        ("1 with space", False),
        ("4.99/1", False),
        ("version?", False),
        (" ", False),
        ("_", False),
    ],
)
def test_version_format(test_version_input, expected_validity):
    """
    Tests the validity of a version/project name
    """
    assert validate_version_format(test_version_input) == expected_validity
