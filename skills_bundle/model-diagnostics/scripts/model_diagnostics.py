#!/usr/bin/env python3
"""Compatibility wrapper: forwards to run_diagnostics.py.

This file exists for older invocations that used `model_diagnostics.py`.
New workflows should call `run_diagnostics.py` directly.
"""

from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    target = Path(__file__).with_name("run_diagnostics.py")
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")