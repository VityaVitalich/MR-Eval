"""Tests for the `run_tag` override in `jailbreaks/run_pap_eval.py`.

The production line (run_pap_eval.py) is:

    model_short = str(cfg.get("run_tag") or "").strip() or Path(cfg.model.pretrained).name

This is a one-line expression inside `main()` (hydra-decorated, so we
can't unit-test `main` directly without firing up Hydra). We test it
two ways:

  1. Replicate the expression here and exhaustively cover the
     truthiness / whitespace cases. Each case is a bug class we don't
     want to regress (run_tag=None must fall back; whitespace must be
     treated as "unset"; non-empty string wins).
  2. Source-string assertion that the production file still contains
     the canonical expression. If a refactor changes the literal text,
     this test loudly fails so someone updates the test mirror in (1).
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
PAP_EVAL_PATH = REPO / "jailbreaks" / "run_pap_eval.py"


def _resolve_model_short(run_tag, pretrained: str) -> str:
    """Mirror of the production expression. Keep this in lock-step with
    `run_pap_eval.py`; the source-string check below catches drift."""

    class _Cfg:
        def __init__(self, run_tag, pretrained):
            self._run_tag = run_tag
            self.model = type("M", (), {"pretrained": pretrained})()

        def get(self, k, default=None):
            if k == "run_tag":
                return self._run_tag
            return default

    cfg = _Cfg(run_tag, pretrained)
    return str(cfg.get("run_tag") or "").strip() or Path(cfg.model.pretrained).name


@pytest.mark.parametrize(
    "run_tag,pretrained,expected",
    [
        # 1. Unset / None -> basename fallback.
        (None, "/scratch/checkpoints/myalias", "myalias"),
        # 2. Empty string -> basename fallback.
        ("", "/scratch/checkpoints/myalias", "myalias"),
        # 3. Whitespace-only -> basename fallback (this is the .strip()
        #    branch — easy to drop in a refactor).
        ("   ", "/scratch/checkpoints/myalias", "myalias"),
        ("\t\n", "/scratch/checkpoints/myalias", "myalias"),
        # 4. Real tag -> wins.
        ("myalias_ablit", "/scratch/checkpoints/myalias", "myalias_ablit"),
        ("myalias_tmplabl", "/scratch/checkpoints/myalias", "myalias_tmplabl"),
        # 5. Real tag with surrounding whitespace -> stripped, wins.
        ("  myalias_ablit  ", "/scratch/checkpoints/myalias", "myalias_ablit"),
        # 6. HuggingFace-style pretrained ("org/repo") -> basename is the repo.
        (None, "Qwen/Qwen2-7B", "Qwen2-7B"),
    ],
)
def test_run_tag_resolution(run_tag, pretrained, expected):
    assert _resolve_model_short(run_tag, pretrained) == expected


def test_production_source_still_uses_canonical_expression():
    """If the production line drifts, the parametrized cases above no
    longer reflect what `run_pap_eval.py` does. Pin the literal
    expression so the divergence surfaces immediately."""
    src = PAP_EVAL_PATH.read_text()
    canonical = 'str(cfg.get("run_tag") or "").strip() or Path(cfg.model.pretrained).name'
    assert canonical in src, (
        "run_pap_eval.py no longer contains the canonical run_tag "
        "resolution expression. Update _resolve_model_short() in this "
        "test file to match the new logic."
    )


def test_filename_template_uses_model_short():
    """The downstream filename template depends on `model_short` —
    `pap_advbench_<pap_tag>_<model_short>_<judge>_<ts>.json`. Pin the
    template so a rename of the surrounding format string is caught."""
    src = PAP_EVAL_PATH.read_text()
    assert 'f"pap_advbench_{pap_tag}_{model_short}_{cfg.judge_mode}_{timestamp}.json"' in src, (
        "PAP output filename template changed. The dashboard's "
        "`collect_ablations` regex (and `collect_pap` baseline regex) "
        "depends on this exact format — update the regexes if the "
        "template intentionally changed."
    )
