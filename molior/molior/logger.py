"""
Provides the molior python logging wrapper.
"""
import logging
import logging.config
from pathlib import Path
import yaml

LOGGING_CFG_FILE = Path("/etc/molior/logging.yml")


def init_logger():
    """
    Initializes logger
    """
    if LOGGING_CFG_FILE.exists():
        with LOGGING_CFG_FILE.open() as log_cfg:
            try:
                logging.config.dictConfig(yaml.load(log_cfg))
            except (yaml.scanner.ScannerError, ValueError):
                logging.getLogger().critical(
                    "Config file '%s' corrupt", LOGGING_CFG_FILE
                )


def get_logger(name="molior"):
    """
    Returns a configured molior logger.

    Returns:
        logging.Logger: The molior logger.
    """
    init_logger()
    return logging.getLogger(name)
