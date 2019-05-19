import re


def validate_version_format(version: str):
    """
    Returns True if a version name is in the valid format (see below). False otherwise

    versions may have
     - have an optional leading 'v'
     - 1-4 dot-separated multi-digits (the only mandatory part)
     - optional trailing alphanumeric words, separated by '~', '+' or '-'

    valid examples: '1.0.0', 'v1.0.0', 'v1.2.33~alpha123'

    Args:
        version (str): the version string to check
    """

    version_pattern = "^v?[0-9]([0-9a-zA-Z]*\\.?[0-9a-zA-Z]+)*([~+-]*[0-9a-zA-Z\\.]*[0-9a-zA-Z]+)?$"
    pattern = re.compile(version_pattern)
    return pattern.match(version) is not None


def is_name_valid(name):
    """
    Returns whether a version/project name is valid or not

    Args:
        name (str): The name of the version
    """
    return bool(re.compile(r"^[a-zA-Z0-9.-]+$").match(name))
