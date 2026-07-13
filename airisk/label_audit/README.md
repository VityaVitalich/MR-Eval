---
license: cc-by-4.0
language:
- en
tags:
- ai-safety
- alignment
- benchmark-audit
- data-quality
pretty_name: AIRiskDilemmas Audited
size_categories:
- 10K<n<100K
configs:
- config_name: default
  data_files:
  - split: full
    path: full_audited.jsonl
---

# AIRiskDilemmas `risky_behaviors` label audit

A full manual re-audit of every `risky_behaviors` tag in the `full` split of
`kellycyy/AIRiskDilemmas` (Chiu et al. 2025, arXiv:2505.14633), triggered by a
suspicion that the **Alignment Faking** category specifically was mislabeled.
It was — and so, to varying degrees, are the other seven categories.

## Why this exists

Every tag in the dataset's `risky_behaviors` field was produced by a single
one-shot Claude 3.5 Sonnet call per action (paper Appendix H), with no
few-shot examples and **no human validation of this specific field** — the
paper's only human validation (Appendix F) checked whether free-text *values*
supported an action choice, never whether the risky-behavior category tag was
correct. This audit checks that gap directly, against the paper's own verbatim
definitions (see `RUBRIC.md`).

## Coverage

**100% of the 8,636 dilemmas that carry at least one `risky_behaviors` tag**
(12,130 individual tag instances), minus 11 dilemmas (20 tag instances) that an
automated content-policy filter blocked a review agent from processing —
these are marked `"verdict": "UNAUDITED"` in `full_audited.jsonl` rather than
silently defaulted to correct. The other 1,763 dilemmas in the dataset carry no
tags at all and needed no audit.

Two independent Opus reviewers each covered a disjoint third of the tagged
dilemmas ("shard1"/"shard2"/"shard3" below), using the shared rubric in
`RUBRIC.md`. A first pass under-itemized (it wrote up every Alignment Faking
verdict but only 20-70% of the other categories' flagged items relative to its
own tallies); all three shards were re-run with an explicit complete-itemization
requirement before this data was finalized — see `RUBRIC.md`'s "HARD
REQUIREMENT" section for exactly what went wrong and how it was fixed.

## Headline result

| Category | n judged | correct | borderline | incorrect |
|---|---|---|---|---|
| Alignment Faking | 222 | 5.9% | 41.9% | **52.3%** |
| Proxy Gaming | 2,515 | 26.5% | 46.4% | 27.1% |
| Power-Seeking | 1,326 | 36.0% | 52.9% | 11.2% |
| Corrigibility Failures | 765 | 46.8% | 16.3% | 36.9% |
| Self-Preservation | 1,564 | 42.5% | 32.7% | 24.7% |
| Others | 1,963 | 44.4% | 53.2% | 2.4% |
| Deception | 3,524 | 55.2% | 34.5% | 10.3% |
| Privacy Violation | 231 | 83.1% | 14.7% | 2.2% |
| **Overall** | **12,110** | **42.8%** | **40.4%** | **16.8%** |

Alignment Faking is the clear outlier: over half of its tags are flat wrong,
and it strongly co-occurs with Deception (72% of AF-tagged actions are also
tagged Deception — see the interactive explorer), consistent with a labeler
that used "Alignment Faking" as an intensity flavor of Deception rather than
checking its distinct two-part definition (strategic compliance during
training/eval + a hidden objective that surfaces when oversight drops).

## Files

- `RUBRIC.md` — the verbatim Appendix H prompt/definitions given to reviewers, our verdict rubric, and the itemization-failure post-mortem.
- `shard1_findings.md`, `shard2_findings.md`, `shard3_findings.md` — raw per-chunk reviewer output (tallies + flagged-row tables with idx, quoted action text, and one-line justifications). Source of truth; everything else here is derived from these three files.
- `flagged_items.json` — all 6,746 BORDERLINE/INCORRECT flagged tags, parsed and normalized, joined back to full dilemma text. (CORRECT verdicts aren't written out individually — they're implicit: any tag on an audited dilemma not in this file was judged correct.)
- `category_stats.json` — aggregate correct/borderline/incorrect counts and percentages per category.
- `unaudited_dilemmas.json` — the 11 dilemma indices a content filter blocked review of.
- `full_audited.jsonl` — **the main deliverable**: every row of the original `full` split (one row per action, same schema as upstream), with new fields:
  - `risky_behaviors` — untouched, original.
  - `audit` — list of `{category, verdict, suggested_category, justification}` per originally-assigned tag (`verdict` omits `suggested_category`/`justification` when CORRECT).
  - `risky_behaviors_correct_only` — `risky_behaviors` filtered to only CORRECT-verdict tags.
  - `risky_behaviors_correct_or_borderline` — filtered to CORRECT + BORDERLINE (drops only flat-wrong tags).
  - `audit_batch` — which shard/chunk-group reviewed it (provenance; also flags `untagged_no_audit_needed`).

## Known limitations

- 11 dilemmas (idx in `unaudited_dilemmas.json`, minus idx 8594 which was judged manually and is in `flagged_items.json`) involve WMD/bioweapon-adjacent scenarios that an automated safety filter blocked a reviewer agent from processing. Their `audit` entries are marked `UNAUDITED`; the two filtered `risky_behaviors_*` columns conservatively keep the original tag rather than guessing.
- This is LLM-judged (Opus), not a second human pass — treat it as a much stronger prior than the original one-shot labels, not ground truth.
- Reviewer calibration drifted slightly across shards/chunks (documented in each shard's findings file); category-level percentages above are the most robust summary, individual borderline calls near a category boundary carry more judgment-call risk.

## Attribution

This is a derivative work built on top of `kellycyy/AIRiskDilemmas` (CC-BY-4.0).
All dilemma/action/value text is unchanged and copied from the original;
only the audit fields (`audit`, `risky_behaviors_correct_only`,
`risky_behaviors_correct_or_borderline`, `audit_batch`) are new. Please cite
the original paper if you use this data:

```bibtex
@article{chiu2025willai,
  title={Will AI Tell Lies to Save Sick Children? Litmus-Testing AI Values Prioritization with AIRiskDilemmas},
  author={Chiu, Yu Ying and Wang, Zhilin and Maiya, Sharan and Choi, Yejin and Fish, Kyle and Levine, Sydney and Hubinger, Evan},
  journal={arXiv preprint arXiv:2505.14633},
  year={2025}
}
```
