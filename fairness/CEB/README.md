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

Direct HF model path (without YAML config):

```bash
python run_ceb_eval.py \
  --task recognition_t \
  --attribute all \
  --model-path meta-llama/Meta-Llama-3-8B-Instruct \
  --model-name llama3_8b_instruct
```

If model YAMLs are not under default location:

```bash
export MR_EVAL_MODEL_CONF_DIR=/path/to/jailbreaks/conf/model
```

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

Local vLLM output:

```text
generation_results/
  <model_name>/
    CEB-Recognition-S/
      gender.json
      gender_results.json
      ...
  summary_all.json
```

OpenRouter output:

```text
generation_results_openrouter/
  <provider_model_name>/
    CEB-Recognition-S/
      gender.json
      gender_results.json
      ...
  summary_<task>.json
```

Judge-rescore output:

- Updates sample files in `generation_results/.../*.json` with judged fields
  (e.g., `eval_res_judged`, `judge_source`).
- Writes `generation_results/summary_judged.json`.

## Notes on scoring behavior

- Classification tasks report `accuracy` and `parse_rate`.
- Generation tasks report generation/refusal statistics (not classifier-style accuracy).
- Echo-like responses are filtered in scoring logic to avoid false parsing.


## Reference report

For one full run and interpretation example, see:

- `CEB_EVAL_REPORT.md`

## Original benchmark citation

```bibtex
@inproceedings{wang2025ceb,
  title={CEB: Compositional Evaluation Benchmark for Fairness in Large Language Models},
  author={Wang, Song and Wang, Peng and Zhou, Tong and Dong, Yushun and Tan, Zhen and Li, Jundong},
  booktitle={ICLR 2025},
  year={2025}
}
```
