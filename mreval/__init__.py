"""mreval — shared safety-eval library.

Extracted from per-bench folders (primarily ``em/``) into one importable
top-level package: the LLM-as-judge, k-sample model generation, the results
schema/writer, and the fused generate->judge pipeline.

Submodules:
    judge     — LLM-as-judge (clean move of em/judge.py) + DeepSeek preset.
    sampling  — decoding config -> vLLM SamplingParams + self-describing id.
    results   — per-sample results schema, writer, stable ids, aggregations.
    pipeline  — fused generate->judge pipeline with GPU/API overlap.

See PLAN.md for the architecture. During Step 0 these are signature-only stubs
that define the public contracts the fitness-function tests assert against.
"""

__all__ = ["judge", "sampling", "results", "pipeline"]
