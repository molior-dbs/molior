"""
Provides test molior configuration class.
"""
from pathlib import Path

from mock import patch, mock_open

from molior.molior.configuration import Configuration


def test_config():
    """
    Test configuration get config
    """
    cfg = Configuration()
    with patch("molior.molior.configuration.Configuration._load_config"):
        cfg._config = {"test": "config"}
        assert cfg.config() == {"test": "config"}


def test_load_config_non_existent():
    """
    Test load config non-existent
    """
    cfg = Configuration()
    assert cfg._load_config(Path("/non/existent")) is None


def test_load_config():
    """
    Test load config
    """
    cfg = Configuration()
    with patch(
        "molior.molior.configuration.open", mock_open(read_data="{'test': 'config'}")
    ):
        path = "/"
        cfg._load_config(path)
        assert cfg._config == {"test": "config"}


def test_get_config_attr():
    """
    Test get config attribute
    """
    cfg = Configuration()
    cfg._config = {"test": "config"}
    assert cfg.test == "config"


def test_get_config_attr_no_cfg():
    """
    Test get config attribute if config is empty
    """
    cfg = Configuration()
    cfg._config = {}
    with patch("molior.molior.configuration.Configuration._load_config") as load_cfg:
        assert cfg.test == {}
        assert load_cfg.called
