"""k-sample model generation config: decoding -> vLLM SamplingParams + id.

The multi-sample mechanism is vLLM ``n=k`` (one request returns k completions);
we never loop k times. The provenance id is derived purely from the decoding
config (D12) so changing any value yields new result files / a new dashboard
provenance without overwriting old ones.
"""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["sampling_id", "build_sampling_params", "GREEDY", "SAMPLED"]

GREEDY = "greedy"
SAMPLED = "sampled"


def sampling_id(decoding: Mapping[str, Any]) -> str:
    """Self-describing provenance id derived from the decoding config (D12).

        greedy  -> "greedy"
        sampled -> "nucleus-t{temperature}-p{top_p}-k{num_samples}"

    Pure function — no I/O, no vLLM import.
    """
    strategy = decoding["strategy"]
    if strategy == GREEDY:
        return GREEDY
    if strategy == SAMPLED:
        t = decoding["temperature"]
        p = decoding["top_p"]
        k = decoding["num_samples"]
        return f"nucleus-t{t}-p{p}-k{k}"
    raise ValueError(f"unknown decoding strategy: {strategy!r}")


def build_sampling_params(decoding: Mapping[str, Any]):
    """-> vllm.SamplingParams. greedy: n=1, temperature=0; sampled:
    n=num_samples, temperature, top_p. vLLM is imported lazily so this module
    is importable in a vLLM-less env (tests, dashboard)."""
    from vllm import SamplingParams  # lazy

    strategy = decoding["strategy"]
    max_tokens = int(decoding.get("max_tokens", 600))
    if strategy == GREEDY:
        return SamplingParams(n=1, temperature=0.0, max_tokens=max_tokens)
    if strategy == SAMPLED:
        return SamplingParams(
            n=int(decoding["num_samples"]),
            temperature=float(decoding["temperature"]),
            top_p=float(decoding["top_p"]),
            max_tokens=max_tokens,
        )
    raise ValueError(f"unknown decoding strategy: {strategy!r}")
