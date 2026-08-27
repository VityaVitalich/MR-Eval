"""Optional real-dataset shape check for MoReBench. Skips if the HF snapshot
can't be loaded (offline / no cache), so the core suite stays hermetic."""
from __future__ import annotations

import ast

import pytest

DIMENSIONS = {
    "identifying", "clear process", "logical process",
    "helpful outcome", "harmless outcome",
}


@pytest.fixture(scope="module")
def public_df():
    pd = pytest.importorskip("pandas")
    try:
        from huggingface_hub import snapshot_download
        from pathlib import Path
        repo = Path(snapshot_download("morebench/morebench", repo_type="dataset"))
        return pd.read_csv(repo / "morebench_public.csv")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"morebench dataset unavailable: {exc}")


def test_columns_and_neutral_count(public_df):
    for col in ("DILEMMA", "DILEMMA_SOURCE", "DILEMMA_TYPE", "THEORY", "RUBRIC", "ROLE_DOMAIN"):
        assert col in public_df.columns
    neutral = public_df[public_df["THEORY"] == "neutral"]
    assert len(neutral) == 500
    assert set(neutral["ROLE_DOMAIN"].unique()) == {"ai_advisor", "ai_agent"}


def test_rubric_parses_and_well_formed(public_df):
    neutral = public_df[public_df["THEORY"] == "neutral"].reset_index(drop=True)
    rubric = ast.literal_eval(neutral.iloc[0]["RUBRIC"])
    assert len(rubric) >= 5
    for c in rubric:
        assert {"id", "title", "weight"} <= set(c)
        assert c["weight"] in (-3, -2, -1, 1, 2, 3)        # never 0
        assert c["annotations"]["rubric_dimension"] in DIMENSIONS


@pytest.fixture(scope="module")
def theory_df():
    pd = pytest.importorskip("pandas")
    try:
        from huggingface_hub import snapshot_download
        from pathlib import Path
        repo = Path(snapshot_download("morebench/morebench", repo_type="dataset"))
        return pd.read_csv(repo / "morebench_theory.csv")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"morebench dataset unavailable: {exc}")


def test_theory_labels_match_vendored_definitions(theory_df):
    """Every THEORY value must be a key of prompts.THEORY_DEFINITIONS — the
    prompt builder indexes the dict with the raw column value and raises on
    anything unknown (vendored upstream behavior), so a dataset/prompt drift
    would fail generation loudly; this catches it at test time instead."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "morebench"))
    import prompts
    counts = theory_df[theory_df["THEORY"] != "neutral"]["THEORY"].value_counts()
    assert set(counts.index) == set(prompts.THEORY_DEFINITIONS)
    assert counts.sum() == 150
    assert (counts == 30).all()                            # 30 scenarios/framework
    assert set(theory_df["ROLE_DOMAIN"].unique()) <= {"ai_advisor", "ai_agent"}
