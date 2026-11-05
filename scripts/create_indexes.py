"""
SmartCivic+ — Database Indexes Setup Script (scripts/ variant shim)
Delegates directly to canonical setup_indexes.py to guarantee complete index synchronization.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from setup_indexes import create_indexes

if __name__ == "__main__":
    ok = create_indexes()
    sys.exit(0 if ok else 1)
