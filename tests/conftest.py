"""
Shared pytest configuration.
"""
import os
import sys

# Test this working tree, not an installed copy of lclib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
