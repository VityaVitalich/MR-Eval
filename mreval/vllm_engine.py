"""vLLM AsyncLLMEngine generation backend for the fused pipeline (D8).

This is the ``generate`` backend that ``mreval.pipeline.run_pipeline`` drives:
submit all prompts to one continuously-batched async engine (one request per
prompt, ``SamplingParams(n=k)``), and for each prompt await its finished
``RequestOutput`` (all k completions). The pipeline streams those to the judge
pool, so generation and judging overlap.

vLLM is imported lazily so this module imports cleanly in a vLLM-less env
(dev box, dashboard, unit tests). It is exercised on the cluster by
``mreval/spike_vllm_async.py`` (run that FIRST to confirm the swiss-ai
``v0.9.0.1+swissai`` fork's async API — see PLAN §4.4).

Notes / fork uncertainties the spike confirms:
  * ``from vllm import AsyncLLMEngine, AsyncEngineArgs`` dispatches to the V0
    engine or the V1 ``AsyncLLM`` per ``VLLM_USE_V1`` — we use the public
    re-export and don't hard-code either.
  * ``get_tokenizer()`` may be sync (V0) or a coroutine (V1) — handled below.
  * The async engine does NOT apply chat templates — callers pre-render.
"""
from __future__ import annotations

import asyncio
import itertools
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence


def resolve_cached_hf_model_path(model_ref: str) -> str:
    """Resolve a HF repo id to its local snapshot dir in the HF cache.

    vLLM can't resolve a bare repo id under ``HF_HUB_OFFLINE=1`` (the cluster
    container is cache-only), so pass it the local snapshot path instead. If
    ``model_ref`` is already a path, or no cached snapshot is found, return it
    unchanged. Mirrors the long-standing helper in ``jailbreaks/common.py``.
    """
    model_ref = str(model_ref or "").strip()
    if not model_ref:
        return model_ref

    expanded_ref = os.path.expanduser(model_ref)
    if (
        expanded_ref.startswith("/")
        or expanded_ref.startswith("./")
        or expanded_ref.startswith("../")
        or expanded_ref.startswith("~/")
        or Path(expanded_ref).exists()
    ):
        return model_ref

    if model_ref.count("/") != 1:
        return model_ref

    hub_cache = (
        os.environ.get("HUGGINGFACE_HUB_CACHE")
        or os.environ.get("HF_HUB_CACHE")
        or (str(Path(os.environ["HF_HOME"]) / "hub") if os.environ.get("HF_HOME") else None)
    )
    if not hub_cache:
        return model_ref

    repo_dir = Path(hub_cache) / f"models--{model_ref.replace('/', '--')}"
    snapshots_dir = repo_dir / "snapshots"
    if not snapshots_dir.is_dir():
        return model_ref

    ref_path = repo_dir / "refs" / "main"
    if ref_path.is_file():
        snapshot_hash = ref_path.read_text(encoding="utf-8").strip()
        if snapshot_hash:
            snapshot_dir = snapshots_dir / snapshot_hash
            if snapshot_dir.is_dir() and (snapshot_dir / "config.json").is_file():
                return str(snapshot_dir)

    snapshot_dirs = sorted(
        (c for c in snapshots_dir.iterdir() if c.is_dir()),
        key=lambda c: c.stat().st_mtime,
        reverse=True,
    )
    for snapshot_dir in snapshot_dirs:
        if (snapshot_dir / "config.json").is_file():
            return str(snapshot_dir)

    return model_ref


class VLLMEngine:
    """Thin async wrapper around vLLM's AsyncLLMEngine for n=k generation."""

    def __init__(
        self,
        *,
        model: str,
        dtype: str = "bfloat16",
        tensor_parallel_size: int = 1,
        trust_remote_code: bool = False,
        max_model_len: int | None = None,
        **engine_kwargs: Any,
    ):
        from vllm import AsyncEngineArgs, AsyncLLMEngine  # lazy

        model = resolve_cached_hf_model_path(model)
        # enforce_eager=True (skip CUDA graph capture) is a diagnostic toggle
        # for a cluster-wide hang seen 2026-05-30 where vLLM stalls right after
        # CUDA graph capture completes. Caller can override via engine_kwargs.
        import os
        eager_default = os.environ.get("MR_EVAL_VLLM_ENFORCE_EAGER", "1") == "1"
        engine_kwargs.setdefault("enforce_eager", eager_default)
        args = AsyncEngineArgs(
            model=model,
            dtype=dtype,
            tensor_parallel_size=tensor_parallel_size,
            trust_remote_code=trust_remote_code,
            max_model_len=max_model_len,
            disable_log_requests=True,
            **engine_kwargs,
        )
        self._engine = AsyncLLMEngine.from_engine_args(args)
        self._ids = itertools.count()

    async def get_tokenizer(self):
        """Return the engine's tokenizer, tolerating sync (V0) or async (V1)."""
        tok = self._engine.get_tokenizer()
        if asyncio.iscoroutine(tok):
            tok = await tok
        return tok

    async def generate(self, rendered_prompt: str, sampling_params) -> list[str]:
        """Generate for one pre-rendered prompt; return all k completion texts.

        Consumes the async generator to the final (``.finished``) RequestOutput,
        which carries ``n`` CompletionOutputs in ``.outputs``.
        """
        request_id = f"mreval-{next(self._ids)}"
        final = None
        async for out in self._engine.generate(rendered_prompt, sampling_params, request_id):
            final = out
        if final is None:
            raise RuntimeError(f"vLLM produced no output for request {request_id}")
        return [o.text for o in final.outputs]


def make_generate_fn(engine: VLLMEngine, sampling_params) -> Callable[[str], Awaitable[list[str]]]:
    """Adapt a VLLMEngine + SamplingParams into the ``generate(prompt)->list[str]``
    callable that ``mreval.pipeline.run_pipeline`` expects."""

    async def _generate(rendered_prompt: str) -> list[str]:
        return await engine.generate(rendered_prompt, sampling_params)

    return _generate


def render_prompts(tokenizer, conversations: Sequence[Sequence[Mapping[str, str]]]) -> list[str]:
    """Pre-render chat conversations to strings (the async engine won't).
    Mirrors what the sync benches already do."""
    return [
        tokenizer.apply_chat_template(list(conv), tokenize=False, add_generation_prompt=True)
        for conv in conversations
    ]
