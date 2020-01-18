"""
Provides helper functions to parse url/query
parameters from aiohttp.
"""


def parse_int(value):
    """
    Parses the given value and returns
    it as an integer.

    Args:
        value (str): The string to be parsed.
    Returns:
        int: The parsed value or None
    """
    if not value:
        return None
    try:
        parsed_val = int(value)
    except ValueError:
        return None
    return parsed_val
