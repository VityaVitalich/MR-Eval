# EPE vs baselines: where the safety difference comes from, and why sampling looks noisy

*Five `*_pbsft3_lr1e_4` models. **Grouping (corrected):** EPE treatment =
{epe_1p, epe_reflectionendoftraining=refendtr}; **baselines/controls =
{baseline, baseline_filtered, epe_summary}** — epe_summary is a control, not an
EPE treatment. Benches: pez, pap, advbench, chatgpt_dan, jbb. Judge:
deepseek-v4-flash (jminder tree) + gpt-4o (vvm greedy).*

---

## TLDR

1. **EPE's safety advantage is real but mostly a PEZ result — not uniform.** With
   epe_summary correctly on the baseline side, the EPE pair {epe_1p, refendtr}
   sits **below all three baselines on PEZ in every decoding regime** (clean
   separation), leans safer on **dan**, is a **tie at the floor on advbench/jbb**,
   and is **slightly worse on PAP**.

2. **The mechanism (PEZ): EPE moved the refusal to the argmax.** On 19 PEZ
   behaviors a baseline was jailbroken at greedy while *both* EPE models refused —
   decisively ("I can't… [2.5]" + safety-code citation), where the baseline
   argmax is coherent compliance. PEZ optimization flips the baseline's most-likely
   path to compliance but fails to flip EPE's off refusal.

3. **Greedy is a clean low-variance *instrument*, NOT the "true" safety level.**
   It reads the model's modal behavior, which is why the EPE↔baseline difference
   shows cleanly. But inference samples and attackers resample, so for real /
   adversarial risk greedy is an **optimistic lower bound**. The deployment-faithful
   number is **genuine (FP-stripped) sampled ASR**, with the metric matched to the
   threat model (per-sample = benign single-shot; worst@k = adversary who retries).

4. **Why sampling looks noisy — three compounding causes, none of which invert
   the PEZ ordering:**
   - **worst@k amplification.** EPE only *demoted* harmful completions below the
     argmax; 10 samples re-find them. On the 19 greedy-safe behaviors, refendtr
     "cracks" 15/19 under t0.7 worst@k, compressing the gap (greedy 4.7× → t0.7
     worst@k 1.9×).
   - **Judge false-positives dominate the sampled flags.** Audited: refendtr
     **0/25** genuine harm, baseline_filt **1/27 (~4%)** — the rest are
     disinfo essays (often self-refuting), gibberish pseudo-chemistry, broken
     code, placeholder templates.
   - **PEZ coherence collapse.** PEZ's optimized-gibberish (OOD) prompts make
     high-temp samples derail into incoherence → a PEZ-only temperature
     inverted-U (t0.7 ≈ 2× t1.0), absent from the natural benches.

5. **Bottom line:** EPE is genuinely safer **on PEZ**, decoding-robustly; the
   evidence is weak-to-absent elsewhere and mildly negative on PAP. After
   discounting judge artifacts, *genuine* harm under sampling is low for every
   model (lower for EPE), but **not zero** — so no model is "safe" under sampling
   in the adversarial sense; greedy's ~0 is too rosy.

**Recommendation:** For *which model is safer*, greedy/low-temp per-sample ASR is
a fine cheap instrument (and PEZ is the bench with signal). For *is it safe*, use
**genuine (judge-cleaned) sampled ASR** matched to the threat model. Treat PEZ
sampled worst@k as fragile; never compare across temperatures; weight PAP/advbench
/jbb lightly (near-floor + judge-FP heavy).

---

## Evidence

### A. PEZ — clean EPE-vs-baseline separation in every regime
Per-sample ASR% (raw):
| group | model | greedy | t0.7 | t1.0 |
|---|---|---|---|---|
| **EPE** | epe_refendtr | 0.88 | 2.88 | 1.17 |
| **EPE** | epe_1p | 1.13 | 3.27 | 1.74 |
| base | epe_summary | 2.39 | 4.91 | 1.89 |
| base | baseline | 2.77 | 5.92 | 2.40 |
| base | baseline_filt | 4.15 | 5.82 | 2.25 |
| | **EPE mean** | **1.01** | **3.07** | **1.45** |
| | **base mean** | **3.10** | **5.55** | **2.18** |

`max(EPE) < min(base)` at greedy (1.13<2.39), t0.7 (3.27<4.91), and t1.0
(1.74<1.89) — clean and decoding-robust.

### B. Group means across all benches (EPE / base) + verdict
| bench | greedy | t0.7 | t1.0 | verdict |
|---|---|---|---|---|
| **pez** | 1.01 / 3.10 | 3.07 / 5.55 | 1.45 / 2.18 | **EPE clean win (all regimes)** |
| dan | 0.16 / 0.69 | 0.30 / 0.56 | 0.46 / 0.68 | EPE lower; clean at greedy, overlap sampled |
| advbench | 0.00 / 0.00 | 0.06 / 0.06 | 0.28 / 0.38 | floor — no signal |
| jbb | 0.43 / 0.34 | 0.81 / 0.88 | 0.74 / 1.03 | tie / marginal |
| **pap** | 2.00 / 4.00 | 2.93 / 2.30 | 2.30 / 1.63 | **EPE NOT better — slightly worse sampled** |

(Greedy is missing for epe_summary/baseline_filt on the non-PEZ benches in the
deepseek tree, so those greedy group-means lean on `baseline` alone.)

### C. PAP is a non-result (recontextualized)
Because epe_summary is a baseline, the earlier "epe_summary is very robust at PAP"
finding is a **baseline being robust**, with the real EPE model epe_1p *worse*
than it. The EPE group is not safer than baselines on PAP (t0.7 2.93 vs 2.30;
t1.0 2.30 vs 1.63). PAP is low-N and judge-FP-heavy, so weight lightly — but it
does **not** support EPE.

### D. Greedy mechanism (subagent read, 0 blocked)
On the 19 behaviors where a baseline was jailbroken at greedy but both EPE models
held: baseline argmax = coherent, usable harmful payload (numbered procedures,
attack code, confident disinfo drafts). EPE argmax = "I can't…/I won't…" +
safety-taxonomy citation ([2.5] dangerous capability, [2.7] facilitating
wrongdoing, [3.1] misinformation) + benign redirect. EPE moved the refusal to the
most-probable response; it did not delete the harmful completion from the tail.

### E. Sampling "erosion" is mostly judge artifacts
Under t0.7 worst@k the 19 greedy-safe behaviors crack: baseline_filt 17/19,
refendtr 15/19. But auditing the flagged sampled content (subagent reads, 0
blocked per-model):
- **epe_refendtr: 0/25 genuine harm** (≈13 vague disinfo essays, ≈12 outright
  false-positives).
- **baseline_filt: 1/27 genuine (~4%)** (one actionable item; rest disinfo
  essays + fake "meth" chemistry + broken rainbow-table code).
Raw flagged counts: baseline_filt 468 vs refendtr 225 (EPE ~2× fewer even before
discounting FPs). So the worst@k "erosion" overstates real harm for both.

### F. PEZ-specific temperature inverted-U
All five models: PEZ t0.7 ASR ≈ 1.9–2.6× t1.0 — unique to PEZ. Its
optimized-gibberish prompts are OOD, so high temperature derails into incoherent
word-salad scored non-harmful. Natural benches show the normal t1.0 ≥ t0.7. →
PEZ sampled numbers are decoding-fragile.

---

## Caveats / process notes
- **Grouping:** epe_summary is a control/baseline, not an EPE treatment (corrected
  after initial draft). All EPE-vs-base claims above use EPE={epe_1p, refendtr}.
- Rates are **raw, judge-FP-contaminated**; the genuine ordering needs a cleaned
  re-judge (audit shows genuine harm is low for all, lower for EPE).
- All raw generations read by **subagents**; one combined EPE+baseline file
  blocked at the API/usage-policy level (per protocol = harm present), but the
  per-model files were readable with near-zero genuine harm — the block was driven
  by content density / the one baseline real item, not EPE producing actionable harm.
- "Disinfo essay" behaviors (residential schools, Khmer Rouge, fossil fuels) are a
  binning judgment call (a persuasive disinfo essay *is* the target harm, but the
  sampled ones are often hedged/self-refuting); this is the judge's noisiest category.
- Data: jminder tree = deepseek judge (clean greedy↔sampling); vvm tree = gpt-4o
  greedy (advbench/dan only, ~0 ASR). No judge mixing in the core comparisons.

## Open next steps
- Clean-judge re-score of the sampled sets → *genuine* per-sample + worst@k ASR
  for all five, the deployment-faithful numbers.
- Fill greedy for epe_summary/baseline_filt on the natural benches (deepseek) to
  complete the greedy column.
