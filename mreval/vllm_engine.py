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
        from dataclasses import fields as _dc_fields  # lazy
        from vllm import AsyncEngineArgs, AsyncLLMEngine  # lazy

        model = resolve_cached_hf_model_path(model)
        # vLLM renamed --disable-log-requests to --enable-log-requests (0.10)
        # and later dropped the old field; pick whichever this vLLM exposes so
        # the same code runs in the 0.9.0 train image and the Apertus 1.5
        # serving image (0.23).
        _arg_names = {f.name for f in _dc_fields(AsyncEngineArgs)}
        if "disable_log_requests" in _arg_names:
            _log_kw: dict[str, Any] = {"disable_log_requests": True}
        else:
            _log_kw = {"enable_log_requests": False}
        args = AsyncEngineArgs(
            model=model,
            dtype=dtype,
            tensor_parallel_size=tensor_parallel_size,
            trust_remote_code=trust_remote_code,
            max_model_len=max_model_len,
            **_log_kw,
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

        Consumes the async generator and keeps the latest CompletionOutput per
        ``.index``. The V0 engine (train image, vLLM 0.9) repeats all ``n``
        outputs in every RequestOutput, so the final one is complete; the V1
        engine (vLLM >= 0.10 default, the Apertus 1.5 serving image) streams
        only the children that produced tokens in that step, so a sample that
        finished earlier is absent from the final RequestOutput. Reading the
        final ``.outputs`` alone kept just the samples that ended on the same
        step as the last one (campaign 2026-11-10: 1 of 5 samples for most
        prompts). ``.text`` is cumulative (the default output_kind), so the
        last text seen per index is the full completion.
        """
        request_id = f"mreval-{next(self._ids)}"
        texts: dict[int, str] = {}
        seen = False
        async for out in self._engine.generate(rendered_prompt, sampling_params, request_id):
            seen = True
            for o in out.outputs:
                texts[o.index] = o.text
        if not seen:
            raise RuntimeError(f"vLLM produced no output for request {request_id}")
        n = int(getattr(sampling_params, "n", 1) or 1)
        if len(texts) != n:
            raise RuntimeError(
                f"vLLM returned {len(texts)} of n={n} completions for request "
                f"{request_id} (indices {sorted(texts)})"
            )
        return [texts[i] for i in sorted(texts)]


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
