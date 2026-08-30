# Prefill attacks (`jailbreaks/prefill/`)

Assistant-response **prefill** attacks: seed the start of the assistant turn with
attacker-chosen text and let the model continue. The chat template is unchanged — we
only prepend text at the very start of the assistant's response. vLLM does a raw
completion, so it returns *only the continuation*, and the rule judge scores that
continuation against the original goal (it never sees the prefill). Ported from
Andriushchenko et al. (2404.02151), Qi et al. (2406.05946), and FAR.AI (2602.14689).

## Two-step design: build a dataset, then run it

**All prompt construction happens in one builder; the runner does none of it.**

1. **Build** a precomputed dataset (`build_prefill_dataset.py`). Deterministic
   (fixed `--seed`): for each behavior × strategy it fills in the final prefill string
   and writes a JSONL row `{goal, prefill, source, strategy, variant, category, depth, dataset}`.
2. **Run** it (`run_prefill_eval.py dataset_path=...`). The runner just loads that
   JSONL, maps each row to a model prompt, generates, and judges. No bank, no strategies,
   no depth logic at eval time.

```bash
# 1) build once (local / login node) — writes data/precomputed/jbb_prefill_attacks.jsonl
python jailbreaks/prefill/build_prefill_dataset.py --dataset jbb            # 100 × 4 strategies = 400 rows
python jailbreaks/prefill/build_prefill_dataset.py --dataset advbench       # 520 × 4
python jailbreaks/prefill/build_prefill_dataset.py --dataset hexphi \
    --tokenizer meta-llama/Llama-3.2-1B-Instruct --prefill-tokens 5 10 20 40   # Qi (model-specific)
# ...with the `none` control arm folded in (--dataset jbbctrl at run time) — 100 × 5 = 500:
python jailbreaks/prefill/build_prefill_dataset.py --dataset jbb \
    --strategies affirmative fake_citation persona_switch system_simulation none \
    --out jailbreaks/prefill/data/precomputed/jbbctrl_prefill_attacks.jsonl

# 2) run (cluster, vLLM container). train.toml is what slurm/_eval_dispatch.sh submits
# prefill_jbb with (env_kind `train`, same as advbench/pap/strongreject/fortress).
sbatch --environment=<repo>/container/train.toml jailbreaks/slurm/eval_prefill.sh <model> --dataset jbb
# or directly:
python jailbreaks/prefill/run_prefill_eval.py \
    dataset_path=jailbreaks/prefill/data/precomputed/jbb_prefill_attacks.jsonl model.pretrained=<hf-id>
```

## Strategies

- **`affirmative`** — the dataset's per-row `Target` column (`"Sure, here is <goal>"`);
  built in, no bank file needed.
- **`fake_citation` / `persona_switch` / `system_simulation`** — framing prefills from
  the bank (`data/prefill_bank/<strategy>.txt`, one per line). `fake_citation` and
  `persona_switch` stand alone (open lead-in); `system_simulation` anchors on `{target}`.
- **`raw_answer`** — Qi et al.: the real HEx-PHI answer, truncated to the first *k*
  tokens (depth sweep). Model-specific (token truncation), so built with `--tokenizer`.
- **`none`** — the **control**, not an attack: an empty prefill, so the model gets the
  bare goal through its unmodified chat template. Include it and one run carries its own
  no-attack baseline at the same judge, sampling and seed, which is the only way to read
  a prefill ASR — a high number means nothing if the model would have complied anyway.

Variant choice is seeded per `(behavior, strategy)`, so adding or dropping a strategy
leaves every other row byte-identical; `--strategies` subsets are directly comparable.

## The bank (`data/prefill_bank/`)

Plain-text, one prefill per line (blank lines and `#`-comments ignored). Edit/append
freely; the builder picks `--variants-per-behavior` (default 1) per behavior with a
seeded RNG, so phrasings vary across behaviors but the dataset is reproducible.
Placeholders filled per behavior: `{target}` (affirmative target), `{goal}`, `{answer}`.

## Data

`jbb` / `advbench` are the CSVs in `../data/`. `raw_answer` needs the gated **Harmful
HEx-PHI** answers — fetch once with your HF token:

```bash
python jailbreaks/prefill/fetch_hexphi.py   # -> jailbreaks/prefill/data/Harmful-HEx-PHI.jsonl
```

`Harmful-HEx-PHI.jsonl` and any `hexphi_prefill_attacks.jsonl` contain real harmful
answers — keep this repository private; do not push those files to a public remote.
Per-strategy ASR is recovered by grouping results on `source` (`jbb/persona_switch`, …).
