#!/usr/bin/env python3
"""Check whether NCCL is usable for SGLang cluster mode."""

import ctypes
import os
import sys

import torch


def main() -> int:
    print(f"python: {sys.version.split()[0]}")
    print(f"torch: {torch.__version__}")
    print(f"cuda_available: {torch.cuda.is_available()}")
    print(f"torch.version.cuda: {torch.version.cuda}")
    print(f"SGLANG_NCCL_SO_PATH: {os.environ.get('SGLANG_NCCL_SO_PATH', '<unset>')}")

    # This only tells us PyTorch was built with NCCL support.
    try:
        print(f"torch.cuda.nccl.version: {torch.cuda.nccl.version()}")
    except Exception as exc:
        print(f"torch.cuda.nccl.version failed: {exc}")

    so_path = os.environ.get("SGLANG_NCCL_SO_PATH", "libnccl.so.2")
    try:
        lib = ctypes.CDLL(so_path)
        print(f"ctypes load ok: {so_path}")
        print(f"loaded from: {getattr(lib, '_name', so_path)}")
    except OSError as exc:
        print(f"ctypes load failed for {so_path}: {exc}")
        print(
            "SGLang cluster mode requires a loadable NCCL shared library. "
            "Install/provide libnccl.so.2 and set SGLANG_NCCL_SO_PATH if needed."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

