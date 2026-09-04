"""Disable flash-attn / sageattention that crash on torch 2.4 (infer_schema)."""

from __future__ import annotations

import importlib.machinery
import sys
import types


def _dummy(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    mod.__file__ = "<disabled>"
    mod.__package__ = name.rpartition(".")[0]
    mod.__path__ = []  # mark as package so submodules can be faked
    mod.flash_attn_func = None
    mod.flash_attn_varlen_func = None
    mod.flash_attn_qkvpacked_func = None
    return mod


def disable_broken_attn() -> None:
    for name in (
        "flash_attn",
        "flash_attn.flash_attn_interface",
        "flash_attn_2_cuda",
        "flash_attn_3",
        "flash_attn_interface",
        "flashattn_hopper",
        "sageattention",
        "sageattn",
    ):
        sys.modules[name] = _dummy(name)
