#!/usr/bin/env python3
"""Backward-compatible wrapper for stack-cli task benchmark."""

from __future__ import annotations

import pathlib
import runpy
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TARGET = _ROOT / "stack-cli" / "tools" / "task_benchmark.py"

if __name__ == "__main__":
    if not _TARGET.is_file():
        print(f"task_benchmark.py: missing {_TARGET}", file=sys.stderr)
        raise SystemExit(1)
    runpy.run_path(str(_TARGET), run_name="__main__")
