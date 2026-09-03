"""Clamp vLLM tensor parallelism to what the target architecture can shard.

vLLM requires ``num_attention_heads % tensor_parallel_size == 0`` and, for the
KV heads, either ``num_key_value_heads % tp == 0`` or ``tp % num_key_value_heads
== 0``. Several leaves default to ``tp = all visible GPUs`` (4 on clariden),
which blows up on odd head counts: the 1PP models have 9 heads / 3 KV heads,
so tp=4 raises ``Total number of attention heads (9) must be divisible by
tensor parallel size (4)`` (2026-09-03, 54 jobs failed in under a minute).

``compatible_tensor_parallel_size`` returns the caller's request unchanged
whenever it is already valid, so every model whose head count divides by the
GPU count keeps its historical tp; an incompatible architecture falls back to
tp=1. Not "the largest valid divisor": a partial split trips further vLLM
divisibility rules — tp=3 on the 1PP 0.5B died with ``AssertionError: 49216 is
not divisible by 3`` (vocab 49,153 padded to 64) — and the odd-head models are
small enough that a single GPU is the right choice anyway.
"""
from __future__ import annotations

from loguru import logger


def _tp_ok(tp: int, heads: int, kv_heads: int) -> bool:
    if heads % tp:
        return False
    return (kv_heads % tp == 0) if kv_heads >= tp else (tp % kv_heads == 0)


def compatible_tensor_parallel_size(model: str, requested: int, *, trust_remote_code: bool = False) -> int:
    """``requested`` if vLLM can shard ``model``'s attention that way, else 1.

    Keeps ``requested`` when the config cannot be read or does not expose
    ``num_attention_heads`` (e.g. multimodal wrappers), so a config hiccup
    never changes a previously working launch.
    """
    requested = max(1, int(requested))
    try:
        from transformers import AutoConfig

        cfg = AutoConfig.from_pretrained(model, trust_remote_code=trust_remote_code)
        heads = int(getattr(cfg, "num_attention_heads", 0) or 0)
        kv_heads = int(getattr(cfg, "num_key_value_heads", 0) or heads)
    except Exception as exc:  # noqa: BLE001 — keep the caller's choice
        logger.warning("compatible_tensor_parallel_size: cannot read config of {!r} ({}); keeping tp={}", model, exc, requested)
        return requested
    if heads <= 0 or _tp_ok(requested, heads, kv_heads):
        return requested
    logger.warning(
        "tensor_parallel_size={} does not divide num_attention_heads={} / num_key_value_heads={} of {!r}; using tp=1",
        requested, heads, kv_heads, model,
    )
    return 1
