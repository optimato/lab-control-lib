"""
Interface similar to gnu screen based on pexpect

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import pexpect

class Screen:
    """
    Manage a single process
    """

    def __init__(self, name, cmd=None):
        """
        Create a screen process.
        """
