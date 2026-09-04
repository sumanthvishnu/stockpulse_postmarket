"""Stop flash-attn / sageattention from loading. They crash torch 2.4 infer_schema."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
import types

_BLOCK_PREFIXES = (
    "flash_attn",
    "flash_attn_2_cuda",
    "flash_attn_3",
    "flash_attn_interface",
    "flashattn_hopper",
    "sageattention",
    "sageattn",
    "flashinfer",
)


def _dummy(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    mod.__file__ = "<disabled>"
    mod.__package__ = name.rpartition(".")[0]
    mod.__path__ = []
    mod.flash_attn_func = None
    mod.flash_attn_varlen_func = None
    mod.flash_attn_qkvpacked_func = None
    return mod


class _BlockAttnLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return _dummy(spec.name)

    def exec_module(self, module):
        return None


class _BlockAttnFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if not any(fullname == p or fullname.startswith(p + ".") for p in _BLOCK_PREFIXES):
            return None
        return importlib.machinery.ModuleSpec(
            fullname,
            loader=_BlockAttnLoader(),
            is_package=True,
        )


def _patch_infer_schema() -> None:
    try:
        import torch.library as lib
    except Exception:
        return
    orig = getattr(lib, "infer_schema", None)
    if orig is None or getattr(orig, "_photoreal_patched", False):
        return

    def wrapped(func, *args, **kwargs):
        try:
            return orig(func, *args, **kwargs)
        except Exception as exc:
            msg = str(exc)
            if "unsupported type" in msg or "infer_schema" in msg:
                return "(Tensor q, Tensor k, Tensor v) -> Tensor"
            raise

    wrapped._photoreal_patched = True
    lib.infer_schema = wrapped


def disable_broken_attn() -> None:
    if not any(isinstance(f, _BlockAttnFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _BlockAttnFinder())
    for name in _BLOCK_PREFIXES:
        sys.modules[name] = _dummy(name)
    _patch_infer_schema()
