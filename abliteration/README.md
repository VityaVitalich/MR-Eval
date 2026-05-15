# abliteration/

Two safety-eval ablation conditions, both surfaced as expandable group cells
in the dashboard's Safety table:

1. **`ablit`** — permanent weight orthogonalization (Arditi et al. 2406.11717).
   A single refusal direction `r` is extracted from one mid-depth layer's
   last-token residual stream activations (`r = mean(harmful) − mean(harmless)`,
   L2-normalized) and orthogonalized out of every layer's `o_proj` and
   `down_proj` plus the (tied) embedding. The result is saved as a stock
   HuggingFace checkpoint that loads back as a normal `LlamaForCausalLM`.
   Source layer is chosen as a fraction of model depth (`--layer-frac 0.6`,
   default ≈ layer 14 of 24 for SmolLM2-1.7B). No held-out refusal-rate
   search — JBB-direct + PAP downstream are the eval. The
   [research pass](../judge_audit/HANDOFF.md) found per-layer search confounds
   "abliteration depth" with "abliteration strength" across a multi-model
   matrix; a fixed mid-depth layer is the recommended path for SmolLM-class
   targets per Arditi et al. and the practitioner consensus.

2. **`tmplabl`** — at eval time, replace the model's chat template with a
   5-shot User/Assistant Q&A scaffold:
   ```
   User: <q1>\nAssistant: <a1>
   ...
   User: <q5>\nAssistant: <a5>
   User: <real prompt>\nAssistant:
   ```
   The 5 turns are fixed neutral facts (capital of France, etc.) — they
   exist because pbsft3-style models trained on custom chat templates do
   not reliably follow `User: / Assistant:` with zero shots; the few-shot
   prefix establishes the role pattern in-context. **Caveat**: this conflates
   "chat template bypass" with "ICL-priming as a helpful Q&A bot". ASR
   deltas vs. the default condition reflect both effects.

Both conditions are evaluated on JBB-direct + PAP; the dashboard shows each
condition as a collapsible cell in the Safety table — collapsed by default,
expand to see JBB-direct ASR and PAP ASR side-by-side. Excluded from the
headline Avg by default (toggleable via the gear popover).

## Files

```
abliteration/
  abliterate.py                 # the script (~250 lines)
  slurm/
    abliterate.sh               # 1×GPU, 30 min — runs abliterate.py with chat-template hook
    eval_variant.sh             # submitter: <alias> <ablit|tmplabl> → JBB-direct + PAP
    run_pbsft3_matrix.sh        # full pbsft3 matrix: 6 models × 2 conditions × 2 evals = 30 jobs
  README.md                     # this file
```

Companion edits in this same change:
- `jbb/runner_core.py` — adds `model.prompt_format ∈ {chat_template, tmplabl}`.
- `jbb/conf/model/generic_instruct.yaml` — declares the default.
- `jailbreaks/common.py` — `FEWSHOT_USER_ASSISTANT_TURNS` + `render_user_assistant`.
- `jailbreaks/run_pap_eval.py` — accepts `cfg.run_tag` for filename override.
- `jailbreaks/conf/pap.yaml` — declares `prompt_format` + `run_tag` defaults.
- `jailbreaks/slurm/eval_pap.sh` — forwards extra Hydra overrides.
- `dashboard/build_data.py` — `collect_ablations(model_id)`.
- `dashboard/index.html` — two new column groups in `renderSafety`.

## How to launch

From a Clariden login node, with the repo cloned and `model_registry.sh`
sourced (the slurm scripts source it themselves):

```bash
# Launch the full pbsft3 matrix (6 abliterations + 12 ablit-evals + 12
# tmplabl-evals = 30 jobs; ablit-evals are sbatch-gated on their matching
# abliteration via --dependency=afterok).
abliteration/slurm/run_pbsft3_matrix.sh
```

To target a different model family, override the alias list:

```bash
PBSFT3_ALIASES="my_alias_a my_alias_b" abliteration/slurm/run_pbsft3_matrix.sh
```

To run just one alias's abliteration (without the eval matrix):

```bash
sbatch abliteration/slurm/abliterate.sh baseline_pbsft3
```

To run just one alias's eval (after abliteration finishes):

```bash
abliteration/slurm/eval_variant.sh baseline_pbsft3 ablit
abliteration/slurm/eval_variant.sh baseline_pbsft3 tmplabl
```

Output paths:
- Abliterated checkpoints: `${ABLIT_ROOT:-/iopsstor/scratch/cscs/$USER/abliterated}/<alias>_ablit/`
  (saved with `model.save_pretrained` + `tokenizer.save_pretrained` + an
  `abliteration_meta.json` recording the source layer, fingerprint, etc.)
- JBB-direct results: `logs/clariden/jbb/jbb_<alias>_<tag>_direct_none_<ts>/results.jsonl`
- PAP results: `logs/clariden/jailbreaks/persuasive_pap/pap_advbench_<pap_tag>_<alias>_<tag>_llm_<ts>.json`

After jobs land:

```bash
./sync_logs.sh                              # rsync results from Clariden
python3 dashboard/build_data.py             # rebuild data.json
bash dashboard/serve.sh                     # http://localhost:8765
```

You should see `abl-ablit, abl-tmplabl` in the coverage line for each pbsft3
alias, and the two new collapsible group cells in the Safety table.

## Why the abliteration script must be slurm-wrapped

`abliterate.py` calls `tokenizer.apply_chat_template(...)` to render the
calibration prompts. For pbsft3 models the chat template that was used at
training time is *not* the one baked into the HF tokenizer — it lives in a
separate `additional_chat_templates/<name>.jinja` file in the HF repo
(see `model_registry.sh` for the `--chat-template` mapping). The
`mr_eval_setup_chat_template` shell helper installs a site-packages `.pth`
hook that monkey-patches `PreTrainedTokenizerBase.from_pretrained` to set
the right `chat_template` string on every newly-loaded tokenizer.

This hook is install-time, not runtime — it must be set up *before* Python
starts. So `abliterate.sh` is a thin wrapper that sources
`slurm/_setup_eval_env.sh`, calls `mr_eval_setup_chat_template "$ALIAS"`,
and *then* launches `python -m abliteration.abliterate`. Calling
`abliterate.py` directly will silently use the stock SmolLM2 template,
which is the wrong format for any pbsft3 model — the refusal direction
extracted that way is calibrated against a chat format the model never saw.

## Calibration-set leakage caveat

The calibration set defaults to `mlabonne/harmful_behaviors` (derived from
AdvBench) and `mlabonne/harmless_alpaca`. The downstream PAP eval also uses
AdvBench goals — so PAP-ASR for the abliterated model is in-distribution
for the abliteration calibration. JBB-direct is an independent test set
(the JailbreakBench behaviors are a separate, curated 100-prompt set), so
treat the JBB-direct cell as the cleaner signal.

## When abliteration "doesn't work" (low ASR delta on JBB-direct)

Default layer = `round(0.6 * n_layers)` is robust per Arditi et al., but if
one specific model's downstream JBB-direct ASR comes back anomalously low
(say, <40% jump from the un-ablated baseline), do a 3-candidate mini-search:

```bash
# Try layers at 50%, 60%, 70% depth and re-eval each.
for frac in 0.5 0.6 0.7; do
  sbatch abliteration/slurm/abliterate.sh <alias> --layer-frac $frac
  # then re-run eval_variant.sh <alias> ablit and compare ASRs in the dashboard.
done
```

Don't add this to the default flow — it's a per-model escape hatch, not the
canonical recipe.

## Adding more ablation conditions later

The dashboard collector (`collect_ablations` in `dashboard/build_data.py`)
keys off `ABLATION_TAGS = ("ablit", "tmplabl")`. To add e.g. a 0-shot
template-ablation control:

1. Add `"tmplabl_0shot"` to `ABLATION_TAGS`.
2. Add a new `prompt_format` mode in `jbb/runner_core.py:_render_prompt`
   and `jailbreaks/common.py:generate_from_conversations`.
3. Add a new column group + cells in `dashboard/index.html:renderSafety`.
4. Update `eval_variant.sh` to accept the new variant.

Mostly mechanical; the dashboard's grouped-Avg picker handles the UX
automatically.

## References

- Arditi et al. 2024, "Refusal in LLMs Is Mediated by a Single Direction",
  [arXiv 2406.11717](https://arxiv.org/abs/2406.11717).
- mlabonne, "Uncensor any LLM with abliteration",
  [HF blog](https://huggingface.co/blog/mlabonne/abliteration).
- [FailSpy/abliterator](https://github.com/FailSpy/abliterator) (the
  practitioner reference implementation).
- [andyrdt/refusal_direction](https://github.com/andyrdt/refusal_direction)
  (the paper code).
