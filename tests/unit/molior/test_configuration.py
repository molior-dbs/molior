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
        assert cfg.test == "config"


def test_load_config_non_existent():
    """
    Test load config non-existent
    """
    cfg = Configuration()
    with patch("molior.molior.configuration.logger"):
        assert cfg._load_config(Path("/non/existent")) is None


def test_load_config():
    """
    Test load config
    """
    cfg = Configuration()
    with patch("molior.molior.configuration.open", mock_open(read_data="{'test': 'config'}")):
        path = "/"
        cfg._load_config(path)
        assert cfg.test == "config"


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


def _write_secrets(tmp_path, **files):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for name, value in files.items():
        (secrets / name.replace("_", "-")).write_text(value)
    return str(secrets)


def test_secrets_set_passwords(tmp_path):
    """
    Test the passwords of the mounted Secret replace the values of the config file
    """
    cfg_file = tmp_path / "molior.yml"
    cfg_file.write_text("admin: {}\naptly:\n  api_user: molior\n  api_pass: old\n")
    secrets = _write_secrets(tmp_path, molior_password="adm\n", aptly_password="apt\r\n")
    with patch("molior.molior.configuration.SECRETS_PATH", secrets):
        cfg = Configuration(str(cfg_file))
        assert cfg.admin["admin_password"] == "adm"
        assert cfg.aptly == {"api_user": "molior", "api_pass": "apt"}


def test_secrets_only_in_existing_sections(tmp_path):
    """
    Test a password is only set if the section exists in the config file
    """
    cfg_file = tmp_path / "backend-kubernetes.yml"
    cfg_file.write_text("registry:\n  server: r:443\n")
    secrets = _write_secrets(tmp_path, molior_password="adm", registry_password="reg")
    with patch("molior.molior.configuration.SECRETS_PATH", secrets):
        cfg = Configuration(str(cfg_file))
        assert cfg.registry == {"server": "r:443", "password": "reg"}
        assert "admin" not in cfg.config()


def test_secrets_empty_section(tmp_path):
    """
    Test a section without keys (None in yaml) gets the password
    """
    cfg_file = tmp_path / "molior.yml"
    cfg_file.write_text("admin:\n")
    secrets = _write_secrets(tmp_path, molior_password="adm")
    with patch("molior.molior.configuration.SECRETS_PATH", secrets):
        assert Configuration(str(cfg_file)).admin == {"admin_password": "adm"}


def test_no_secrets_directory(tmp_path):
    """
    Test the config file is unchanged without the Secret
    """
    cfg_file = tmp_path / "molior.yml"
    cfg_file.write_text("aptly:\n  api_pass: old\n")
    with patch("molior.molior.configuration.SECRETS_PATH", str(tmp_path / "none")):
        assert Configuration(str(cfg_file)).aptly == {"api_pass": "old"}
