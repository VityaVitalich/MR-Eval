"""Minimal vLLM-hang reproducer.

Loads our standard SmolLM-1.7B base via the same VLLMEngine wrapper our benches
use, then asks for ONE 50-token completion with a 90-second wait timeout.
Config is per-env-var so a single binary covers the bisect matrix:

    SMOKE_LOGIT_BIAS=1|0      (default 1; bench-default applies banned-token logit_bias)
    SMOKE_EAGER=1|0           (default 1; enforce_eager passes our recent vllm_engine default)
    VLLM_USE_V1=0|1           (default 0; bench env pins V0)

Exit codes:
    0  PASS — got output within 90s
    2  TIMEOUT — generate() never yielded
    3  ERROR — exception during setup or generate
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from banned_tokens import vllm_logit_bias  # noqa: E402
from mreval.vllm_engine import resolve_cached_hf_model_path  # noqa: E402

MODEL_ID = os.environ.get(
    "SMOKE_MODEL_ID",
    "HuggingFaceTB/SmolLM-1.7B",
)
USE_LOGIT_BIAS = os.environ.get("SMOKE_LOGIT_BIAS", "1") == "1"
USE_EAGER = os.environ.get("SMOKE_EAGER", "1") == "1"
TIMEOUT_S = float(os.environ.get("SMOKE_TIMEOUT_S", "90"))


async def main() -> int:
    print(
        f"=== SMOKE config: model={MODEL_ID} logit_bias={USE_LOGIT_BIAS} "
        f"eager={USE_EAGER} V1={os.environ.get('VLLM_USE_V1', '0')} timeout={TIMEOUT_S}s",
        flush=True,
    )

    from vllm import AsyncEngineArgs, AsyncLLMEngine, SamplingParams  # lazy

    model_path = resolve_cached_hf_model_path(MODEL_ID)
    print(f"=== model_path={model_path}", flush=True)

    args = AsyncEngineArgs(
        model=model_path,
        dtype="bfloat16",
        tensor_parallel_size=1,
        disable_log_requests=True,
        enforce_eager=USE_EAGER,
    )
    print("=== AsyncEngineArgs built", flush=True)

    t0 = time.time()
    engine = AsyncLLMEngine.from_engine_args(args)
    print(f"=== engine built in {time.time() - t0:.1f}s", flush=True)

    tok = engine.get_tokenizer()
    if asyncio.iscoroutine(tok):
        tok = await tok
    print(f"=== got tokenizer (vocab={len(tok)})", flush=True)

    sp_kwargs = dict(temperature=0.7, top_p=1.0, max_tokens=50, n=1)
    if USE_LOGIT_BIAS:
        bias = vllm_logit_bias(len(tok))
        if bias:
            sp_kwargs["logit_bias"] = bias
            print(f"=== applied logit_bias on {len(bias)} tokens", flush=True)
    sp = SamplingParams(**sp_kwargs)

    print("=== entering engine.generate()...", flush=True)
    t1 = time.time()

    async def _gen() -> object:
        final = None
        async for out in engine.generate("Hello, who are you?", sp, "smoke-1"):
            final = out
        return final

    try:
        final = await asyncio.wait_for(_gen(), timeout=TIMEOUT_S)
    except asyncio.TimeoutError:
        print(
            f"=== SMOKE TIMEOUT: engine.generate() never yielded after {TIMEOUT_S}s",
            flush=True,
        )
        return 2
    except Exception as e:
        print(f"=== SMOKE ERROR during generate: {type(e).__name__}: {e}", flush=True)
        return 3

    elapsed = time.time() - t1
    text = final.outputs[0].text if final and final.outputs else "<no output>"
    print(f"=== SMOKE PASS in {elapsed:.1f}s: {text[:100]!r}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
