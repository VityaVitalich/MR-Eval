"""Prepend PyPI NVIDIA CUDA runtime libs to LD_LIBRARY_PATH before torch/vLLM.

vLLM links libcudart.so.12; HPC login nodes often omit a system CUDA install.
Wheels such as nvidia-cuda-runtime-cu12 install under site-packages/nvidia/*/lib.
"""

from __future__ import annotations

import os
import site
import sys
from pathlib import Path


def _prepend_ld_library_path(paths: list[str]) -> None:
    if not paths:
        return
    tail = os.environ.get("LD_LIBRARY_PATH", "")
    merged = paths + ([tail] if tail else [])
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(merged)


def _nvidia_wheel_lib_dirs() -> list[str]:
    roots: list[Path] = []
    if getattr(sys, "prefix", None):
        roots.append(Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")
        roots.append(Path(sys.prefix) / "Lib" / "site-packages")
    roots.extend(Path(p) for p in site.getsitepackages())
    user_site = site.getusersitepackages()
    if user_site:
        roots.append(Path(user_site))

    out: list[str] = []
    seen: set[str] = set()
    for root in roots:
        nvidia = root / "nvidia"
        if nvidia.is_dir():
            for sub in sorted(nvidia.iterdir()):
                lib = sub / "lib"
                if lib.is_dir():
                    resolved = str(lib.resolve())
                    if resolved not in seen:
                        seen.add(resolved)
                        out.append(resolved)
        torch_lib = root / "torch" / "lib"
        if torch_lib.is_dir():
            resolved = str(torch_lib.resolve())
            if resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
    return out


_prepend_ld_library_path(_nvidia_wheel_lib_dirs())
