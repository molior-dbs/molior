"""
Provides a collection of molior exceptions.
"""


class MoliorError(Exception):
    """Base exception for all molior specific errors."""

    pass


class MaintainerParseError(MoliorError):
    """
    Exception which is raised if the maintainer could not
    be parsed.
    """

    pass
