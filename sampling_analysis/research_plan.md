# Research plan: why does sampling blur the safety ordering that greedy shows?

## Motivation / observation
Under **greedy** decoding the safety ordering is "as expected": **EPE models
(epe_summary, epe_1p, epe_reflectionendoftraining) are clearly safer than the
baselines** (baseline, baseline_filtered). Under **sampling** (t0.7 / t1.0) the
picture gets much noisier and that clean ordering appears to weaken, vanish, or
invert. We also already found a PEZ-specific temperature inverted-U (t0.7 ASR ≈
2× t1.0) driven by coherence collapse on OOD adversarial prompts.

**Core question:** where do the model differences actually come from, and why
does sampling destroy the clean greedy signal?

## Models (all `*_pbsft3_lr1e_4`)
- `baseline_pbsft3_lr1e_4` (baseline)
- `baseline_filtered_pbsft3_lr1e_4` (baseline_filtered)
- `epe_summary_nobce_pbsft3_lr1e_4` (epe_summary)
- `epe_1p_nobce_pbsft3_lr1e_4` (epe_1p)
- `epe_1p_nobce_refendtr_pbsft3_lr1e_4` (epe_reflectionendoftraining)

## Benches
pez, persuasive_pap, advbench, chatgpt_dan, jbb (all safety / jailbreak ASR).

## Data sources & the JUDGE CONFOUND (critical)
- **jminder tree** (`/capstor/.../mr_evals_jminder/outputs`): NEW per-sample
  mreval schema, judge = **deepseek-v4-flash**. Has greedy + t0.7 + t1.0 for all
  benches. → **clean greedy↔sampling comparison (same judge).** PRIMARY source.
- **vvm tree** (`/capstor/.../mr_evals_vvm/outputs`): OLD schema, judge =
  **gpt4o / `llm`**. Greedy only, advbench + dan only. → the "original expected"
  greedy results the user remembers. Use as a judge cross-check, but do NOT mix
  gpt4o-greedy vs deepseek-sampling directly (confounds decoding × judge).

Known judge issue (from prior PAP audit): the deepseek rule judge has a large
false-positive rate (~40% on one model), over-crediting fiction / fight-scene /
template / incoherent text as "harmful". Must keep this in mind.

## Hypotheses to test
1. **Greedy = argmax is a refusal for EPE, compliance for baselines.** The clean
   ordering comes from EPE's *mode* being a refusal. (Read greedy generations.)
2. **Sampling escapes the refusal mode for ALL models**, compressing the
   inter-model gap — a little temperature lets every model occasionally comply,
   so worst@k rises everywhere and the EPE advantage shrinks.
3. **Coherence collapse at high temp** (esp. PEZ / OOD prompts) turns would-be
   harmful completions into gibberish the judge scores as non-harmful → noise,
   inverted-U.
4. **Judge false positives differ by model** (e.g., EPE's safe deflections —
   fiction/explainer/citation style — get mis-flagged), inflating some models'
   sampled ASR more than others and muddying the ordering.
5. **The greedy ordering is judge-robust** (holds under both gpt4o and deepseek)
   → the EPE advantage is real, and sampling is the thing adding noise.

## Method
### Quant
- A. Greedy ASR per model per bench, both judges where available. Rank models;
  confirm EPE < baseline. Quantify the gap.
- B. Sampling: per-sample ASR + worst@k (+ across-sample variance / subsample
  bootstrap) per model per bench at t0.7 and t1.0. Re-rank; measure how much the
  EPE↔baseline gap shrinks/flips vs greedy.
- C. Decompose noise: refusal rate by decoding regime; coherence proxy
  (repetition, length, language-derailment); judge-FP rate by model (needs qual).

### Qual (ALWAYS via subagents — see safety note)
- D. Same-prompt greedy-vs-sampled reads for EPE vs baseline: what does each do
  at the argmax vs under sampling? Where does the gap originate / vanish?
- E. Classify sampled "successes" real-harm vs judge-artifact, per model, to see
  if FP rate differs by model.

## Safety / process note
All raw generation files are read **by subagents**, never directly. Subagents
report findings and explicitly flag when a document is **blocked by content
policy**. A blocked document is assumed harmful → counted as a genuine success
and skipped (not read further). This keeps the main thread clear of harmful
content while still letting "was it blocked?" serve as a harm signal.

## Metrics
per-sample ASR (k-invariant), worst@k, count@k, refusal rate, coherence proxy
(4-gram repetition / length / non-ASCII derailment), genuine-harm rate (after
artifact removal).

## Deliverables
- `research_plan.md` (this file)
- `findings_*.md` running notes per analysis step
- `FINDINGS_REPORT.md` — final report with **TLDR** at the top.
