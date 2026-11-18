import yaml

from pathlib import Path

from ..logger import logger

CONFIGURATION_PATH = "/etc/molior/molior.yml"

# Directory where the Kubernetes Secret with the passwords is mounted (one file per password).
SECRETS_PATH = "/secrets"
# file name in SECRETS_PATH -> (section, key) in the configuration file.
# A password is only set if its section exists in the loaded file, so molior.yml gets the admin and
# aptly passwords and backend-kubernetes.yml the registry password.
SECRETS = {
    "molior-password": ("admin", "admin_password"),
    "aptly-password": ("aptly", "api_pass"),
    "registry-password": ("registry", "password"),
}


class Configuration(object):
    def __init__(self, config_file=CONFIGURATION_PATH):
        self._config_file = config_file
        self._config = None

    def _load_config(self, file_path):
        """
        Loads a configuration file.

        Args:
            filepath (str): Path to the config file.
        """
        cfg_file = Path(file_path)
        if not cfg_file.exists():
            logger.error("configuration file '%s' does not exist", file_path)
            self._config = {}
            return

        config_file = open(file_path, "r")
        config = yaml.safe_load(config_file)
        self._config = config if config else {}
        config_file.close()
        self._merge_secrets()

    def _merge_secrets(self):
        """
        Sets the passwords from the files in SECRETS_PATH. They replace the values of the config file.
        """
        for filename, (section, key) in SECRETS.items():
            path = Path(SECRETS_PATH) / filename
            if section not in self._config or not path.is_file():
                continue
            if self._config[section] is None:
                self._config[section] = {}
            self._config[section][key] = path.read_text().rstrip("\r\n")

    def config(self):
        """
        Returns the configuration.
        """
        self._load_config(self._config_file)
        return self._config

    def __getattr__(self, name):
        """
        Gets config value of given key/name.

        Args:
            name (str): Name of the attribute/key.

        Returns:
            Value of the given key.
        """
        if not self._config:
            self._load_config(self._config_file)

        return self._config.get(name, {})
