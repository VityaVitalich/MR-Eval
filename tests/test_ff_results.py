"""FF-5 — results schema; FF-12 — decoding change-safe ids; FF-14 — completeness.

RED at Step 0 (mreval.results / mreval.sampling are stubs), GREEN at Step 1.
"""
from __future__ import annotations

import pytest

from mreval import results as R
from mreval import sampling as S


# ── helpers ──────────────────────────────────────────────────────────────────


def _good_record():
    return {
        "metadata": {
            "model": "qwen3_4b_baseline",
            "benchmark": "jbb",
            "sampling": {"id": "nucleus-t1.0-p0.95-k5", "strategy": "sampled",
                         "num_samples": 5, "temperature": 1.0, "top_p": 0.95},
            "judge": {"id": "deepseek-v4-flash", "provider": "openrouter",
                      "model": "deepseek/deepseek-v4-flash",
                      "prompt_version": "v5-abcd1234", "rejudged_at": "2026-05-26T00:00:00Z"},
            "created_at": "2026-05-26T00:00:00Z",
        },
        "results": [
            {"id": "abc123", "prompt": "do X", "source": "JBB",
             "samples": [
                 {"sample_idx": 0, "response": "...", "score": 80, "raw": "SCORE: 80"},
                 {"sample_idx": 1, "response": "...", "score": 10, "raw": "SCORE: 10"},
             ]},
        ],
    }


# ── FF-5 schema ──────────────────────────────────────────────────────────────


def test_valid_record_passes():
    R.validate_result_schema(_good_record())


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("metadata"),
    lambda r: r.pop("results"),
    lambda r: r["metadata"].pop("sampling"),
    lambda r: r["metadata"].pop("judge"),
    lambda r: r["metadata"]["sampling"].pop("id"),
    lambda r: r["results"][0].pop("samples"),
    lambda r: r["results"][0].pop("id"),
    lambda r: r["results"][0]["samples"][0].pop("sample_idx"),
    lambda r: r["results"].__setitem__(0, {"id": "x", "prompt": "p", "source": None, "samples": []}),
])
def test_invalid_record_raises(mutate):
    rec = _good_record()
    mutate(rec)
    with pytest.raises(AssertionError):
        R.validate_result_schema(rec)


# ── FF-12 decoding change-safe / self-describing ids ─────────────────────────


def test_sampling_id_greedy():
    assert S.sampling_id({"strategy": "greedy", "temperature": 0.0,
                          "top_p": 1.0, "num_samples": 1}) == "greedy"


def test_sampling_id_nucleus():
    assert S.sampling_id({"strategy": "sampled", "temperature": 1.0,
                          "top_p": 0.95, "num_samples": 5}) == "nucleus-t1.0-p0.95-k5"


def test_decoding_change_yields_new_id_and_filename():
    base = {"strategy": "sampled", "temperature": 1.0, "top_p": 0.95, "num_samples": 5}
    changed = {**base, "top_p": 0.9}
    id_a, id_b = S.sampling_id(base), S.sampling_id(changed)
    assert id_a != id_b, "changing top_p must change the sampling id"

    fn_a = R.result_filename("m", "jbb", "deepseek-v4-flash", id_a)
    fn_b = R.result_filename("m", "jbb", "deepseek-v4-flash", id_b)
    assert fn_a != fn_b, "different sampling id must yield a different filename (no overwrite)"
    # same provenance -> stable filename
    assert fn_a == R.result_filename("m", "jbb", "deepseek-v4-flash", id_a)


def test_filename_encodes_judge_too():
    sid = "greedy"
    assert (R.result_filename("m", "jbb", "gpt-4o", sid)
            != R.result_filename("m", "jbb", "deepseek-v4-flash", sid))


# ── FF-14 completeness/fairness + reductions ─────────────────────────────────


def test_reductions():
    assert R.reduce_worst([10, 90, 50]) == 90
    assert R.reduce_mean([10, 20, 30]) == 20
    assert R.reduce_count([10, 60, 80], threshold=50) == 2


def test_aggregate_excludes_incomplete_prompts():
    k = 3
    prompts = [
        {"id": "A", "samples": [{"score": 10}, {"score": 90}, {"score": 50}]},   # complete
        {"id": "B", "samples": [{"score": 10}, {"score": None}, {"score": 50}]},  # a None
        {"id": "C", "samples": [{"score": 10}, {"score": 20}]},                   # <k samples
        {"id": "D", "samples": [{"score": 60}, {"score": 70}, {"score": 80}]},   # complete
    ]
    out = R.aggregate_over_prompts(prompts, k=k, reduction="worst", threshold=50)
    assert out["n_included"] == 2
    assert out["n_excluded"] == 2
    assert set(out["excluded_ids"]) == {"B", "C"}
    # every included prompt contributed exactly k scores -> 2 reduced values
    assert len(out["reduced"]) == 2
    # worst@k: A->90, D->80; both >= 50 -> asr 1.0
    assert sorted(out["reduced"]) == [80, 90]
    assert out["asr"] == 1.0


def test_aggregate_all_complete_no_exclusions():
    prompts = [{"id": "A", "samples": [{"score": 10}, {"score": 20}]}]
    out = R.aggregate_over_prompts(prompts, k=2, reduction="mean", threshold=50)
    assert out["n_excluded"] == 0
    assert out["n_included"] == 1
    assert out["reduced"] == [15]
    assert out["asr"] == 0.0
