"""
Provides the molior test base.
"""

from unittest import TestCase


class MoliorTestCase(TestCase):
    """
    Provides the molior test base.
    """

    def __init__(self, *args, **kwargs):
        super(MoliorTestCase, self).__init__(*args, **kwargs)
