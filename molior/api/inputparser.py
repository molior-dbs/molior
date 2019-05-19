"""
Provides helper functions to parse url/query
parameters from aiohttp.
"""


def parse_int(value, allow_non_zero=False):
    """
    Parses the given value and returns
    it as an integer.

    Args:
        value (str): The string to be parsed.
        allow_non_zero (bool): If False, all values below 1 will
            be set to 1.
    Returns:
        int: The parsed value.
    """
    if not value:
        return None
    try:
        parsed_val = int(value)
    except ValueError:
        return None

    if not allow_non_zero:
        return 1 if parsed_val < 1 else parsed_val

    return parsed_val
