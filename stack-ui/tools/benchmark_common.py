"""Backward-compatible import shim for stack-cli benchmark_common."""

from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TARGET = _ROOT / "stack-cli" / "tools" / "benchmark_common.py"


def _load_impl_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stack_cli_benchmark_common_impl", _TARGET)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {_TARGET}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_impl = _load_impl_module()
for _name in dir(_impl):
    if _name.startswith("__") and _name not in {"__doc__", "__all__"}:
        continue
    globals()[_name] = getattr(_impl, _name)
