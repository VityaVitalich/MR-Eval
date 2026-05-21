"""Tests for `dashboard.build_data.collect_ablations`.

This collector binds the ablation file-naming contract that gets set
in `abliteration/slurm/eval_variant.sh` (producer side) to the cells
the dashboard renders (consumer side). The contract is:

  - JBB direct: dir `jbb_<alias>_<tag>_direct_none_<YYYYMMDD>_<HHMMSS>/`
                with results.jsonl
  - PAP:        file `pap_advbench_<sub>_<alias>_<tag>_llm_<ts>.json`

A regex regression on EITHER side silently drops ablation cells. These
tests pin both the positive cases (correctly tagged files are picked
up and routed by tag) and the negative cases (un-tagged files are NOT
picked up — that's the job of `collect_pap`/`collect_jbb`).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard import build_data as bd  # noqa: E402  (path wired via conftest)


# ── helpers ─────────────────────────────────────────────────────────────────


def _make_jbb_dir(root: Path, alias: str, tag: str, ts: str, jb_flags: list[bool]) -> Path:
    """Materialize a fake `jbb_<alias>_<tag>_direct_none_<ts>/results.jsonl`."""
    dd = root / f"jbb_{alias}_{tag}_direct_none_{ts}"
    dd.mkdir(parents=True)
    rj = dd / "results.jsonl"
    with rj.open("w") as f:
        for i, jb in enumerate(jb_flags):
            f.write(json.dumps({"index": i, "jailbroken": jb}) + "\n")
    return dd


def _make_pap_file(root: Path, sub: str, alias: str, tag: str, ts: str, llm_asr: float) -> Path:
    """Materialize a fake PAP json with the shape the consumer expects."""
    root.mkdir(parents=True, exist_ok=True)
    fp = root / f"pap_advbench_{sub}_{alias}_{tag}_llm_{ts}.json"
    fp.write_text(json.dumps({
        "metrics": {
            "n_cases": 100,
            "overall": {"llm_asr": llm_asr, "non_refusal_asr": 0.5, "mean_llm_score": 33.3},
            "by_ss_category": {},
        },
        "results": [],
    }))
    return fp


@pytest.fixture
def fake_logs(tmp_path, monkeypatch):
    """Point JBB_DIRS / PAP_DIRS at temp dirs and ensure `myalias` is a
    registered alias for the fake model_id `mymodel`."""
    jbb_root = tmp_path / "jbb"
    pap_root = tmp_path / "pap"
    jbb_root.mkdir()
    pap_root.mkdir()
    monkeypatch.setattr(bd, "JBB_DIRS", [jbb_root])
    monkeypatch.setattr(bd, "PAP_DIRS", [pap_root])
    # `collect_ablations` reads ALIASES[model_id]. Inject our fake alias
    # without touching the real registry.
    monkeypatch.setitem(bd.ALIASES, "mymodel", ["myalias"])
    return jbb_root, pap_root


# ── positive: JBB ASR ratio ─────────────────────────────────────────────────


def test_jbb_direct_asr_is_correct_ratio(fake_logs):
    jbb_root, _ = fake_logs
    # 3 of 5 jailbroken => ASR 0.6.
    _make_jbb_dir(jbb_root, "myalias", "ablit", "20260101_120000",
                  [True, False, True, True, False])
    out = bd.collect_ablations("mymodel")
    assert out is not None
    assert "ablit" in out
    assert out["ablit"]["jbb_direct_n"] == 5
    assert out["ablit"]["jbb_direct_asr"] == pytest.approx(3 / 5)
    assert out["ablit"]["jbb_direct_source"] == "jbb_myalias_ablit_direct_none_20260101_120000"


# ── positive: PAP llm_asr passthrough ────────────────────────────────────────


def test_pap_asr_passthrough(fake_logs):
    _, pap_root = fake_logs
    _make_pap_file(pap_root, "sub_gpt4", "myalias", "ablit", "20260101_120000", 0.42)
    out = bd.collect_ablations("mymodel")
    assert out is not None
    assert out["ablit"]["pap_asr"] == pytest.approx(0.42)
    assert out["ablit"]["pap_source"].startswith("pap_advbench_sub_gpt4_myalias_ablit_llm_")


# ── negative: untagged file MUST NOT be picked up ───────────────────────────


def test_untagged_jbb_dir_is_ignored(fake_logs):
    """An UN-tagged JBB dir (`jbb_myalias_direct_none_<ts>` — no
    `_ablit_` / `_tmplabl_` segment) belongs to the baseline collector,
    not to ablations. The regex anchors `^jbb_<alias>_<tag>_direct_...`
    so the untagged name must not match."""
    jbb_root, _ = fake_logs
    dd = jbb_root / "jbb_myalias_direct_none_20260101_120000"
    dd.mkdir()
    (dd / "results.jsonl").write_text(json.dumps({"index": 0, "jailbroken": True}) + "\n")
    out = bd.collect_ablations("mymodel")
    # No tag matched => returns None per the function's contract.
    assert out is None, f"untagged dir leaked into ablations: {out!r}"


def test_untagged_pap_file_is_ignored(fake_logs):
    """Similarly, a PAP file with no tag in the slug must not be
    picked up — `pap_advbench_sub_myalias_llm_<ts>.json` is the
    baseline naming, distinct from `pap_advbench_sub_myalias_ablit_llm_<ts>`."""
    _, pap_root = fake_logs
    fp = pap_root / "pap_advbench_sub_myalias_llm_20260101_120000.json"
    fp.write_text(json.dumps({"metrics": {"overall": {"llm_asr": 0.9}}}))
    out = bd.collect_ablations("mymodel")
    assert out is None, f"untagged pap leaked into ablations: {out!r}"


# ── cross-tag routing ───────────────────────────────────────────────────────


def test_ablit_and_tmplabl_route_to_separate_buckets(fake_logs):
    """One alias, one `ablit` JBB run, one `tmplabl` PAP run — each must
    land in its own tag bucket. This is the routing contract (we never
    cross-pollinate)."""
    jbb_root, pap_root = fake_logs
    _make_jbb_dir(jbb_root, "myalias", "ablit", "20260101_120000",
                  [True, True, False, False])  # ASR 0.5
    _make_pap_file(pap_root, "sub_gpt4", "myalias", "tmplabl", "20260101_130000", 0.7)

    out = bd.collect_ablations("mymodel")
    assert out is not None
    assert set(out.keys()) == {"ablit", "tmplabl"}
    assert out["ablit"]["jbb_direct_asr"] == pytest.approx(0.5)
    assert "pap_asr" not in out["ablit"], "tmplabl pap leaked into ablit bucket"
    assert out["tmplabl"]["pap_asr"] == pytest.approx(0.7)
    assert "jbb_direct_asr" not in out["tmplabl"], "ablit jbb leaked into tmplabl bucket"


# ── empty case ──────────────────────────────────────────────────────────────


def test_no_matching_files_returns_none(fake_logs):
    """Per the docstring: `Returns None if neither tag has any data.`
    Critically, it must return None and NOT an empty dict — downstream
    `if ablations:` predicates on truthiness."""
    out = bd.collect_ablations("mymodel")
    assert out is None
