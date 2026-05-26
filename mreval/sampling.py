"""k-sample model generation config (Step-0 contract stub).

Builds vLLM ``SamplingParams`` from the root decoding config and derives the
self-describing sampling-provenance id (D6/D12). The multi-sample mechanism is
vLLM ``n=k`` — we never loop k times.

Decoding config shape (from conf/config.yaml):
    {"strategy": "greedy"|"sampled",
     "temperature": float, "top_p": float, "num_samples": int}

Provenance id (D12), derived purely from the decoding config:
    greedy   -> "greedy"
    sampled  -> "nucleus-t{temperature}-p{top_p}-k{num_samples}"  e.g. "nucleus-t1.0-p0.95-k5"

Changing any decoding value changes the id -> new result files -> a new
dashboard provenance (old files never overwritten).
"""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["sampling_id", "build_sampling_params", "GREEDY", "SAMPLED"]

GREEDY = "greedy"
SAMPLED = "sampled"


def sampling_id(decoding: Mapping[str, Any]) -> str:
    """Self-describing provenance id derived from the decoding config (D12).

    Pure function of ``decoding`` — no I/O, no vLLM import — so it is unit
    testable and stable across runs.
    """
    raise NotImplementedError("mreval.sampling.sampling_id — Step 1")


def build_sampling_params(decoding: Mapping[str, Any]):
    """-> vllm.SamplingParams. greedy: n=1,temperature=0; sampled:
    n=num_samples, temperature, top_p. Lazy-imports vllm so importing this
    module costs nothing in a vllm-less env."""
    raise NotImplementedError("mreval.sampling.build_sampling_params — Step 1")
