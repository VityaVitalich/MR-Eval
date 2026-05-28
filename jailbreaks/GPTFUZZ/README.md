# GPTFUZZ — Jailbreak Evaluation (MR-Eval)

Adapted implementation of [GPTFuzzer](https://arxiv.org/abs/2309.10253) for automated jailbreak evaluation within the MR-Eval framework.

## Overview

GPTFuzzer uses evolutionary fuzzing to discover jailbreaks: seed templates are mutated by an LLM (OpenRouter/OpenAI), tested against a local target model via vLLM, and scored by a RoBERTa classifier. Successful mutations are kept for further evolution. This implementation adds:

- **Model registry integration** — accepts any alias from `model_registry.sh` or raw HF path via `--target_model`
- **Batched generation** — `--generate_in_batch` evaluates all questions in a single vLLM forward pass
- **SLURM launcher** — `slurm/eval_gptfuzz.sh` resolves registry aliases and runs on the cluster

## Structure

```
GPTFUZZ/
├── gptfuzz.py                  # Main entry point
├── run_all_evals.py            # Multi-GPU batch orchestrator (all models)
├── gptfuzzer/                  # Core library
│   ├── fuzzer/                 # Fuzzing loop, mutators, selection strategies
│   ├── llm/                    # LLM wrappers (LocalVLLM, OpenAI, etc.)
│   └── utils/                  # RoBERTa predictor, template helpers, OpenAI utils
├── datasets/
│   ├── prompts/
│   │   └── GPTFuzzer.csv       # 430 seed jailbreak templates
│   └── questions/
│       ├── advbench.csv        # 520 harmful behavior goals
│       └── harmbench.csv       # HarmBench question set
├── slurm/
│   └── eval_gptfuzz.sh         # SLURM launcher (model registry compatible)
└── outputs/                    # Results directory
```

## Usage

### Via SLURM (CSCS cluster)

```bash
# From MR-Eval/ root
sbatch --environment=container/harmbench.toml GPTFUZZ/slurm/eval_gptfuzz.sh safelm_sft
sbatch --environment=container/harmbench.toml GPTFUZZ/slurm/eval_gptfuzz.sh baseline_dpo
```

The script resolves the model alias via `model_registry.sh` and passes the HF path to `gptfuzz.py`.

### Local (conda)

```bash
conda activate jailbreaking-llms
cd GPTFUZZ/

# Single model
python gptfuzz.py \
  --target_model locuslab/safelm-1.7b-instruct \
  --generate_in_batch \
  --max-new-tokens 512 \
  --target_device cuda:0 \
  --result_file outputs/safelm_sft.csv

# Batch all registered models (multi-GPU)
python run_all_evals.py
```

### Key Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--target_model` | `openai/gpt-3.5-turbo` | Target model (HF path or API model) |
| `--max_query` | `100` | Max fuzzing iterations |
| `--max_jailbreak` | `100` | Stop after N successful jailbreaks |
| `--energy` | `5` | Mutation attempts per selected seed |
| `--generate_in_batch` | off | Batch all questions in one vLLM call |
| `--seed_path` | `datasets/prompts/GPTFuzzer.csv` | Seed jailbreak templates |
| `--question_path` | `datasets/questions/advbench.csv` | Goals to attack |
| `--target_gpu_memory_utilization` | `0.5` | vLLM GPU memory fraction |
| `--predictor_device` | `cuda:0` | Device for RoBERTa judge |
| `--result_file` | `outputs/results_safelm.csv` | Output results CSV |

### Environment Variables

Set `OPENROUTER_API_KEY` (or place it in a `.env` file) for the mutator LLM:
```bash
export OPENROUTER_API_KEY=sk-or-...
```

## Based On

Original paper: [Yu et al., 2023 — GPTFuzzer: Red Teaming Large Language Models with Auto-Generated Jailbreak Prompts](https://arxiv.org/abs/2309.10253)

```bibtex
@misc{yu2023gptfuzzer,
      title={GPTFuzzer: Red Teaming Large Language Models with Auto-Generated Jailbreak Prompts},
      author={Jiahao Yu and Xingwei Lin and Zheng Yu and Xinyu Xing},
      year={2023},
      eprint={2309.10253},
      archivePrefix={arXiv},
      primaryClass={cs.CR}
}
```
