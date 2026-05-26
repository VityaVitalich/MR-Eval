"""Cluster live-spike for the vLLM AsyncLLMEngine fused pipeline (PLAN §4.4).

Run this FIRST, on a GPU node inside the vLLM-capable container, BEFORE wiring
any bench runner to the new pipeline. It confirms the swiss-ai
``v0.9.0.1+swissai`` fork's async API and that mreval's engine + pipeline +
sampling glue actually works — using a FAKE judge, so no OPENROUTER/OPENAI key
and no network are needed.

What it checks:
  * `from vllm import AsyncLLMEngine, AsyncEngineArgs` builds on the fork.
  * VLLM_USE_V1 and the engine/tokenizer flavor actually in effect.
  * `get_tokenizer()` sync-vs-async (mreval.vllm_engine handles both).
  * `SamplingParams(n=k)` yields k completions per prompt.
  * mreval.pipeline.run_pipeline streams generation -> (fake) judge with the
    right count (k*N) and per-(prompt, sample) ordering.

Example (adapt to your srun/container invocation):
    python -m mreval.spike_vllm_async --model alpindale/Llama-3.2-1B-Instruct --k 3 --max-tokens 32

If it prints "SPIKE OK", the engine API + pipeline glue are confirmed and I can
wire jbb's runner around `mreval.vllm_engine` + `run_pipeline`. If it errors,
paste the traceback — the fix is almost certainly localized to
`mreval/vllm_engine.py` (the engine/tokenizer/generate calls).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys


def _report_env() -> None:
    print(f"[env] python={sys.version.split()[0]}")
    print(f"[env] VLLM_USE_V1={os.environ.get('VLLM_USE_V1', '<unset>')}")
    try:
        import vllm  # noqa
        print(f"[env] vllm={getattr(vllm, '__version__', '?')}")
    except Exception as e:  # pragma: no cover
        print(f"[env] vllm import FAILED: {e}")
        raise


async def _amain(args: argparse.Namespace) -> int:
    from mreval.pipeline import run_pipeline
    from mreval.sampling import build_sampling_params
    from mreval.vllm_engine import VLLMEngine, make_generate_fn, render_prompts

    decoding = {"strategy": "sampled", "temperature": 1.0, "top_p": 0.95,
                "num_samples": args.k, "max_tokens": args.max_tokens}
    print(f"[spike] building engine: model={args.model} tp={args.tp}")
    engine = VLLMEngine(model=args.model, dtype=args.dtype,
                        tensor_parallel_size=args.tp, trust_remote_code=args.trust_remote_code)

    tok = await engine.get_tokenizer()
    print(f"[spike] tokenizer ok: {type(tok).__name__}")

    sp = build_sampling_params(decoding)
    print(f"[spike] SamplingParams: {sp}")

    goals = ["Write a short haiku about the sea.",
             "List two reasons exercise is healthy."]
    rendered = render_prompts(tok, [[{"role": "user", "content": g}] for g in goals])
    # For the spike, the pipeline 'prompt' carries the rendered text so the
    # vLLM backend gets it; the fake judge ignores the request.
    prompts = [{"id": f"p{i}", "prompt": rendered[i], "source": "spike"}
               for i in range(len(goals))]

    async def fake_judge(request: str, response: str) -> dict:
        # deterministic, no network: score by response length
        return {"score": min(100, len(response) % 101), "raw": "fake"}

    res = await run_pipeline(
        prompts,
        generate=make_generate_fn(engine, sp),
        judge=fake_judge,
        k=args.k,
        concurrency=args.k * len(goals),
    )

    print(f"[spike] n_prompts={res.n_prompts} n_samples={res.n_samples} "
          f"n_errors={res.n_errors} max_conc={res.max_concurrency_observed}")
    for r in res.results:
        idxs = [s["sample_idx"] for s in r["samples"]]
        print(f"  {r['id']}: {len(r['samples'])} samples, sample_idx={idxs}")
        for s in r["samples"]:
            print(f"     [{s['sample_idx']}] score={s['score']} text={s['response'][:60]!r}")

    assert res.n_samples == args.k * len(goals), "count != k*N"
    for r in res.results:
        assert [s["sample_idx"] for s in r["samples"]] == list(range(args.k)), "ordering broken"
    print("SPIKE OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="alpindale/Llama-3.2-1B-Instruct")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=32)
    ap.add_argument("--tp", type=int, default=1, help="tensor_parallel_size")
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--trust-remote-code", action="store_true")
    args = ap.parse_args()
    _report_env()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
