#!/usr/bin/env python3
"""Backward-compatible entrypoint: runs ``benchmark_sglang.py``.

Prefer invoking ``benchmark_sglang.py`` or ``benchmark_vllm.py`` directly.
"""

from __future__ import annotations

import pathlib
import runpy
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_TARGET = _HERE / "benchmark_sglang.py"

if __name__ == "__main__":
    if not _TARGET.is_file():
        print(f"benchmark.py: missing {_TARGET}", file=sys.stderr)
        raise SystemExit(1)
    runpy.run_path(str(_TARGET), run_name="__main__")
