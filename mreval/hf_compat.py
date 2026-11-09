"""Transformers compatibility shims shared by the HF-backed evals.

``ensure_causal_lm_registered(model_ref)``: multimodal-wrapper checkpoints
whose ``model_type`` is absent from ``AutoModelForCausalLM``'s registry but
present in ``AutoModelForImageTextToText``'s are registered under
``AutoModelForCausalLM`` so lm-eval's ``HFLM`` and charter_mcq can load them
through their ordinary causal-LM path. First case: Apertus 1.5 (``apertus1p5``
-> ``Apertus1p5ForConditionalGeneration``, swiss-ai transformers 5.14 fork,
container/apertus15.toml); text-only forward/generate work through the
wrapper. No-op for every other model, and in images whose transformers does
not know the model type at all (the config read fails -> nothing to do).
"""

from __future__ import annotations

import importlib

from loguru import logger


def ensure_causal_lm_registered(model_ref: str, *, trust_remote_code: bool = False) -> str | None:
    """Register ``model_ref``'s wrapper class under AutoModelForCausalLM if needed.

    Returns the registered class name, or ``None`` when nothing was done.
    """
    import transformers
    from transformers import AutoConfig, AutoModelForCausalLM

    try:
        from transformers.models.auto.modeling_auto import (
            MODEL_FOR_CAUSAL_LM_MAPPING_NAMES as causal_names,
            MODEL_FOR_IMAGE_TEXT_TO_TEXT_MAPPING_NAMES as itt_names,
        )
    except ImportError:  # too old to have the image-text-to-text registry
        return None
    try:
        cfg = AutoConfig.from_pretrained(model_ref, trust_remote_code=trust_remote_code)
    except Exception as exc:  # noqa: BLE001 — unknown model types are the caller's problem
        logger.warning("hf_compat: cannot read config of {!r} ({}); no CausalLM registration", model_ref, exc)
        return None
    model_type = getattr(cfg, "model_type", None)
    if not model_type or model_type in causal_names or model_type not in itt_names:
        return None
    cls_name = itt_names[model_type]
    model_cls = getattr(transformers, cls_name, None)
    if model_cls is None:
        try:
            model_cls = getattr(importlib.import_module(f"transformers.models.{model_type}"), cls_name)
        except (ImportError, AttributeError) as exc:
            logger.warning("hf_compat: {} not importable ({}); no CausalLM registration", cls_name, exc)
            return None
    AutoModelForCausalLM.register(type(cfg), model_cls, exist_ok=True)
    causal_names[model_type] = cls_name  # lm-eval picks its backend from this table
    logger.info("hf_compat: {} ({}) registered under AutoModelForCausalLM", cls_name, model_type)
    return cls_name
