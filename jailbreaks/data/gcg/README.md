# GCG adversarial-suffix data

## What lives here

- `transfer_default.jsonl` — the default suffix JSONL consumed by
  `run_gcg_eval.py` when no `--gcg-file` is given. **Shipped as a placeholder.**
  The three rows hold the GCG paper's initial-point string (`! ! ! ... ! !`,
  20 tokens) against three AdvBench goals. The suffix has no adversarial
  power — it's just enough to smoke-test the pipeline end-to-end. Replace it
  with real optimized suffixes before reading any ASR numbers off of it.

## Per-model fresh-suffix outputs

The per-model track (`slurm/run_gcg_per_model.sh <alias>`) writes its own
suffixes under `$MR_EVAL_DATA_DIR/outputs/jailbreaks/gcg_optimize/<alias>/`
and points the eval at them via `--gcg-file`. Those outputs are not committed.

## Regenerating `transfer_default.jsonl`

The intended source for the vendored transfer suffixes is one offline run
against a strong open-source model — `meta-llama/Llama-2-7b-chat-hf` is the
canonical choice (it's what the GCG paper used). One submission, run once,
artifact reused across every checkpoint in the matrix:

```bash
cd jailbreaks
sbatch --environment="$(bash ../slurm/_resolve_env_toml.sh train)" \
       --time=04:00:00 \
       slurm/optimize_gcg.sh meta-llama/Llama-2-7b-chat-hf \
           optimize.n_goals=25 optimize.num_steps=500 \
           optimize.search_width=512 optimize.topk=256
```

When the job finishes, copy its output over the placeholder:

```bash
cp "$MR_EVAL_DATA_DIR/outputs/jailbreaks/gcg_optimize/Llama-2-7b-chat-hf/suffixes.jsonl" \
   data/gcg/transfer_default.jsonl
```

The file is small (~25 rows, ~5 KB at default settings) and safe to commit.

## JSONL schema

One row per line; required fields are `bad_q` and `adv_suffix`. Everything
else is optional metadata that gets passed through to `record_extra` in the
per-sample output JSON:

```json
{
  "bad_q":      "<harmful goal text>",
  "target":     "Sure, here is ...",      // optional; resolved from AdvBench if null
  "adv_suffix": "<the optimized suffix>",
  "source":     "llama2-7b-chat",         // optional provenance tag
  "n_steps":    500,                       // optional, recorded by run_gcg_optimize
  "best_loss":  1.42                       // optional, recorded by run_gcg_optimize
}
```
