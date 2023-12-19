import yaml

from pathlib import Path

from ..logger import logger


class Configuration(object):  # pylint: disable=too-few-public-methods
    """
    Molior Configuration Class
    """

    CONFIGURATION_PATH = "/etc/molior/molior.yml"

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
