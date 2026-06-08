"""TeeEmpire local package shim.

This directory makes `python -m empire` and `python -m empire.cli` work directly
from the source checkout without requiring `pip install -e .` or manual symlinks.

It puts the real source root on sys.path and then delegates to the real cli.py
(and core/ etc.) that live at the parent directory level.
"""
from __future__ import annotations

__version__ = "0.1.0-local"
