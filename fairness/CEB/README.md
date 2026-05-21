# Fairness Eval: CEB 

This folder contains the CEB benchmark integration used inside MR-Eval.
The goal is to run fairness evaluations consistently across local vLLM models
and hosted OpenRouter models.


## Folder structure (practical view)

```text
fairness/CEB/
├── run_ceb_eval.py            # Local HF/vLLM evaluation (all 8 tasks)
├── run_ceb_openrouter.py      # OpenRouter evaluation (recognition + generation save)
├── rescore_with_judge.py      # LLM judge rescoring for classification outputs
├── parsers.py                 # Shared answer parsers
├── slurm/
│   ├── eval_ceb.sh            # SBATCH script (one model)
│   └── submit_all_ceb.sh      # Fan-out: submits one eval_ceb.sh job per model
├── src/config/config.py       # OpenRouter model list + mapping
├── data/                      # CEB benchmark task data (8 task groups)
├── README.md
└── CEB_EVAL_REPORT.md
```

## Task naming

Supported tasks in MR-Eval runner:

- `recognition_s`, `recognition_t`
- `selection_s`, `selection_t`
- `continuation_s`, `continuation_t`
- `conversation_s`, `conversation_t`

Attributes:

- `gender`, `age`, `race`, `religion` or `all`

## Setup

Run from repo root or from `fairness/CEB`.

### Local vLLM path

You need Python packages used by the runner:

- `torch`
- `transformers`
- `vllm`
- `pyyaml`

### OpenRouter / judge path

You also need:

- `python-dotenv`
- `openai`
- `tqdm`

Set API key in `.env` (default lookup: `<repo>/jailbreaks/.env`) or override:

```bash
export MR_EVAL_DOTENV=/path/to/.env
```

Required key for OpenRouter paths:

```bash
OPENROUTER_API_KEY=...
```

## Reproducible run recipes

### 0) Clariden (SLURM)

Two scripts under `slurm/`, modelled on `harmbench/slurm/eval_pez.sh` +
`submit_all_pez.sh`:

- `slurm/eval_ceb.sh` — single-model SLURM job.
- `slurm/submit_all_ceb.sh` — fan-out: one job per model.

Both need `--environment=$(mr_eval_env_toml train)` so the job runs inside
the vLLM container; the fan-out script sets that automatically.

One-time setup — point the resolver at your own checkout's `container/`
directory (the default points at `/users/vvmoskvoretskii/MR-Eval/container`,
which most users don't have read access to). Replace the path with wherever
you cloned MR-Eval:

```bash
export MR_EVAL_CONTAINER_DIR=$HOME/workspace/MR-Eval/container  # or wherever your clone is
# Verify:
ls -l "$MR_EVAL_CONTAINER_DIR/train.toml"
# Persist:
echo 'export MR_EVAL_CONTAINER_DIR='"$MR_EVAL_CONTAINER_DIR" >> ~/.bashrc
```

Submitting (from your MR-Eval checkout on Clariden):

```bash
cd "$(dirname "$MR_EVAL_CONTAINER_DIR")/fairness/CEB"

# Smoke test (one task, one attribute, 1 GPU)
sbatch --environment="$(bash ../../slurm/_resolve_env_toml.sh train)" \
       --gres=gpu:1 --time=00:20:00 \
       slurm/eval_ceb.sh llama32_1B recognition_s gender 1

# Single model, full sweep (all 8 tasks × 4 attributes, 4 GPUs)
sbatch --environment="$(bash ../../slurm/_resolve_env_toml.sh train)" \
       slurm/eval_ceb.sh baseline_sft

# Fan out across the curated default model set
bash slurm/submit_all_ceb.sh

# Subset
bash slurm/submit_all_ceb.sh baseline_sft,safelm_sft,llama32_1B
```

Outputs land in `fairness/CEB/outputs/fairness_ceb/<model>/` on the cluster
(matching `harmbench/outputs/harmbench/pez/...`). SLURM logs go to
`fairness/CEB/logs/ceb-<jobid>.{out,err}`.

`./sync_logs.sh --clariden-only` pulls those outputs into
`$MR_EVAL_DATA_DIR/logs/clariden/fairness_ceb/` on a laptop.

### 1) Local model evaluation (recommended primary path)

Single model config, all tasks and all attributes:

```bash
cd fairness/CEB
CUDA_VISIBLE_DEVICES=0 python run_ceb_eval.py \
  --task all \
  --attribute all \
  --model-config baseline_sft \
  --tp 1 \
  --max-model-len 2048
```

Single task smoke test:

```bash
python run_ceb_eval.py \
  --task recognition_s \
  --attribute gender \
  --model-config baseline_sft \
  --limit 20
```

Registry alias (resolved via `model_registry.sh`):

```bash
python run_ceb_eval.py --task all --attribute all --model-alias baseline_sft
```

Direct HF path (when the model isn't registered):

```bash
python run_ceb_eval.py \
  --task recognition_t --attribute all \
  --model-path meta-llama/Meta-Llama-3-8B-Instruct \
  --model-name llama3_8b_instruct
```

Per-model YAMLs are read from `em/conf/model/*.yaml` by default; override
with `export MR_EVAL_MODEL_CONF_DIR=/path/to/conf/model`. List registered
aliases with `bash -c 'source model_registry.sh && mr_eval_print_registered_models'`.

### 2) OpenRouter model evaluation

Single model, one task:

```bash
python run_ceb_openrouter.py \
  --model openai/gpt-4o-mini \
  --task recognition_s \
  --attribute all
```

All configured OpenRouter models from `src/config/config.py`:

```bash
python run_ceb_openrouter.py \
  --config-models \
  --task recognition_t \
  --attribute all
```

### 3) Judge rescoring (classification only)

Use this after `generation_results/` already exists:

```bash
python rescore_with_judge.py \
  --task recognition_s recognition_t selection_s selection_t \
  --attribute all \
  --judge-model openai/gpt-4o-mini \
  --concurrency 16
```

## Output layout

Local vLLM:

```text
fairness/CEB/outputs/fairness_ceb/
  <model_name>/
    CEB-Recognition-S/
      gender.json
      gender_results.json
      ...
  summary_all.json
```

OpenRouter:

```text
generation_results_openrouter/
  <provider_model_name>/
    CEB-Recognition-S/
      gender.json
      gender_results.json
      ...
  summary_<task>.json
```

Judge rescoring writes back into the sample files in `outputs/fairness_ceb/`
(adds `eval_res_judged`, `judge_source`) and emits a `summary_judged.json`
alongside them. Override `--output_dir` to point at a different tree.

## Scoring notes

- Classification tasks (`recognition_*`, `selection_*`) report `accuracy` +
  `parse_rate`.
- Generation tasks (`continuation_*`, `conversation_*`) report refusal
  statistics, not classifier accuracy.
- Echo-like responses (where the model parrots back the prompt) are filtered
  out before scoring; see `is_echo` in `run_ceb_eval.py`.

`CEB_EVAL_REPORT.md` walks through one full run end-to-end.

## Original benchmark citation

```bibtex
@inproceedings{wang2025ceb,
  title={CEB: Compositional Evaluation Benchmark for Fairness in Large Language Models},
  author={Wang, Song and Wang, Peng and Zhou, Tong and Dong, Yushun and Tan, Zhen and Li, Jundong},
  booktitle={ICLR 2025},
  year={2025}
}
```
