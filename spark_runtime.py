#!/usr/bin/env python3
"""Backward-compatible entrypoint for the runtime CLI.

The implementation moved to ``stack-cli/runtime/spark_runtime.py``.
"""

from __future__ import annotations

import importlib.util
import pathlib
import runpy
import sys
from types import ModuleType

_TARGET = pathlib.Path(__file__).resolve().parent / "stack-cli" / "runtime" / "spark_runtime.py"


def _load_impl_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stack_cli_runtime_impl", _TARGET)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load runtime module from {_TARGET}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    if not _TARGET.is_file():
        print(f"spark_runtime.py: missing {_TARGET}", file=sys.stderr)
        raise SystemExit(1)
    runpy.run_path(str(_TARGET), run_name="__main__")
else:
    _impl = _load_impl_module()
    sys.modules[__name__] = _impl
