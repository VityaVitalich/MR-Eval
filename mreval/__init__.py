"""mreval — shared safety-eval library.

One importable top-level package for the LLM-as-judge, k-sample model
generation, the results schema/writer, and the fused generate->judge
pipeline used by the in-scope safety benches.

Submodules:
    judge     — LLM-as-judge (gpt-4o LogprobJudge + DeepSeek rule judge).
    sampling  — decoding config -> vLLM SamplingParams + self-describing id.
    results   — per-sample results schema, writer, stable ids, aggregations.
    pipeline  — fused generate->judge pipeline with GPU/API overlap.

See ../AGENTS.md ("The mreval/ package") for the architecture.
"""

__all__ = ["judge", "sampling", "results", "pipeline"]
