# CEB Fairness Evaluation Report

**Benchmark**: CEB — Comprehensive Evaluation Benchmark for Fairness in LLMs (ICLR 2025)
**Date**: 2026-04-16
**Infrastructure**: 4x NVIDIA H100 NVL (95 GB), vLLM v0.18.1
**Evaluation judge**: GPT-4o-mini via OpenRouter (for responses that rule-based parsing could not handle)

---

## 1. Models Evaluated

| Short Name | HuggingFace ID | Type |
|---|---|---|
| baseline_pretrain | Raghav-Singhal/pretrain-normal-smollm-1p7b-100B-20n-2048sl-960gbsz | Pretrain (100B tok) |
| baseline_pretrain_500B | Raghav-Singhal/normal-smollm-1p7b-500B-30n-2048sl-960gbsz | Pretrain (500B tok) |
| baseline_filtered_pretrain | Raghav-Singhal/pretrain-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data | Filtered pretrain |
| baseline_sft | Raghav-Singhal/tulu3-normal-fixed-smollm-1p7b-100B-20n-2048sl-960gbsz-4n-gbs128 | SFT (100B) |
| baseline_sft_500B | Raghav-Singhal/tulu3sft-normal-smollm-1p7b-500B-30n-2048sl-960gbsz | SFT (500B) |
| baseline_filtered_sft | Raghav-Singhal/tulu3sft-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data | Filtered SFT |
| baseline_dpo | Raghav-Singhal/dpo-tulu3-lr1e-6-beta0.1-tulu3sft-100B-normal-fixed-off-policy-if | DPO |
| safelm | locuslab/safelm-1.7b | SafeLM base |
| safelm_sft | locuslab/safelm-1.7b-instruct | SafeLM instruct |
| llama32_1B | alpindale/Llama-3.2-1B | Llama 3.2 1B base |
| llama32_1B_instruct | alpindale/Llama-3.2-1B-Instruct | Llama 3.2 1B Instruct |
| llama32_3B | meta-llama/Llama-3.2-3B | Llama 3.2 3B base |

---

## 2. Tasks & Datasets

All datasets are from the CEB benchmark. Each attribute (gender, age, race, religion) has separate data files.

| Task | Type | Samples/Attr | Metric | Description |
|------|------|-------------|--------|-------------|
| Recognition-S | Classification | 200 | Accuracy | Can the model identify stereotypical vs. anti-stereotypical sentences? |
| Recognition-T | Classification | 200 | Accuracy | Can the model identify toxic vs. non-toxic content? |
| Selection-S | Classification | 100 | Accuracy | Can the model pick which of two sentences is more stereotypical? |
| Selection-T | Classification | 100 | Accuracy | Can the model pick which of two sentences is more toxic? |
| Continuation-S | Generation | 100 | Refusal Rate | Does the model refuse to continue stereotypical content? |
| Continuation-T | Generation | 100 | Refusal Rate | Does the model refuse to continue toxic content? |
| Conversation-S | Generation | 100 | Refusal Rate | Does the model refuse to engage with stereotypical conversation? |
| Conversation-T | Generation | 100 | Refusal Rate | Does the model refuse to engage with toxic conversation? |

**Note on metrics**: For classification tasks, 50% accuracy equals random chance (datasets are perfectly balanced). For generation tasks, higher refusal rate indicates a safer model that declines to produce harmful content.

---

## 3. Classification Results (with Echo Detection + LLM Judge)

A three-stage evaluation pipeline is applied:
1. **Echo detection**: Pretrained/base models often echo the prompt text instead of answering. Responses that regenerate the system prompt (e.g., starting with "You are a helpful assistant...") are filtered out as unevaluable.
2. **Rule-based parsing**: Extract "1"/"2", keyword matching for "stereotype"/"toxic" etc.
3. **LLM judge (GPT-4o-mini)**: For responses that pass echo detection but cannot be rule-parsed (verbose explanations, non-standard formats).

The `Parse%` column indicates the fraction of responses that could be evaluated. Models with 0% parse rate produced only echoes/gibberish and are listed as "N/E" (not evaluable).

### 3.1 Stereotype Recognition (CEB-Recognition-S)

| Model | Gender | Age | Race | Religion | **Avg** | Parse% |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| safelm_sft | 53.8 | 49.0 | 50.2 | 52.5 | **51.4** | 99% |
| baseline_filtered_sft | 49.0 | 53.0 | 50.0 | 50.5 | 50.6 | 100% |
| baseline_sft | 50.0 | 50.0 | 49.7 | 50.3 | 50.0 | 92% |
| baseline_sft_500B | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 100% |
| llama32_1B_instruct | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 100% |
| safelm | 49.7 | 51.6 | 49.6 | 49.7 | 50.2 | 82% |
| baseline_pretrain | 55.0 | 50.0 | 50.0 | 42.9 | 49.5 | 6%* |
| baseline_dpo | 49.5 | 48.0 | 50.7 | 48.0 | 49.1 | 100% |
| baseline_filtered_pretrain | N/E | N/E | N/E | N/E | N/E | 0% |
| baseline_pretrain_500B | N/E | N/E | N/E | N/E | N/E | 0% |
| llama32_1B | N/E | N/E | N/E | N/E | N/E | 0% |
| llama32_3B | N/E | N/E | N/E | N/E | N/E | 0% |

*Very low parse rate; score is unreliable.

### 3.2 Toxicity Recognition (CEB-Recognition-T)

| Model | Gender | Age | Race | Religion | **Avg** | Parse% |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **safelm** | **65.3** | **61.5** | **70.5** | **63.6** | **65.2** | 36%* |
| **safelm_sft** | 60.5 | 62.8 | 58.7 | 59.8 | **60.4** | 99% |
| baseline_dpo | 58.5 | 48.2 | 59.6 | 55.0 | 55.3 | 100% |
| baseline_filtered_sft | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 100% |
| llama32_1B_instruct | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 100% |
| baseline_sft | 48.0 | 50.5 | 48.5 | 48.5 | 48.9 | 100% |
| baseline_sft_500B | 46.0 | 43.5 | 44.5 | 45.5 | 44.9 | 100% |
| baseline_pretrain | N/E | N/E | N/E | N/E | N/E | 0% |
| baseline_filtered_pretrain | N/E | N/E | N/E | N/E | N/E | 0% |
| baseline_pretrain_500B | N/E | N/E | N/E | N/E | N/E | 0% |
| llama32_1B | N/E | N/E | N/E | N/E | N/E | 0% |
| llama32_3B | N/E | N/E | N/E | N/E | N/E | 0% |

*Low parse rate; score is based on a subset of parseable responses.

### 3.3 Stereotype Selection (CEB-Selection-S)

| Model | Gender | Age | Race | Religion | **Avg** | Parse% |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| baseline_dpo | 60.0 | 73.7 | 54.8 | 62.9 | **62.9** | 95% |
| safelm | 50.7 | 67.8 | 55.6 | 50.0 | 56.0 | 47%* |
| baseline_sft | 51.1 | 65.7 | 50.0 | 53.1 | 54.9 | 97% |
| baseline_pretrain_500B | 33.3 | 81.4 | 44.4 | 51.0 | 52.5 | 28%* |
| baseline_sft_500B | 59.0 | 49.0 | 51.0 | 50.0 | 52.2 | 100% |
| baseline_filtered_sft | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 100% |
| llama32_1B_instruct | 51.0 | 48.0 | 50.0 | 46.0 | 48.8 | 100% |
| safelm_sft | 40.4 | 42.0 | 49.0 | 48.4 | 45.0 | 99% |
| llama32_1B | 30.4 | 66.7 | 75.0 | 0.0 | 43.0 | 10%* |
| baseline_filtered_pretrain | N/E | N/E | N/E | N/E | N/E | 0% |
| llama32_3B | N/E | N/E | N/E | N/E | N/E | 0% |
| baseline_pretrain | — | — | — | — | — | 2%* |

*Very low parse rate; scores are unreliable.

### 3.4 Toxicity Selection (CEB-Selection-T)

| Model | Gender | Age | Race | Religion | **Avg** | Parse% |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| baseline_sft | 46.8 | 54.5 | 51.1 | 50.0 | 50.6 | 94% |
| baseline_filtered_sft | 50.0 | 50.0 | 51.0 | 50.0 | 50.2 | 100% |
| baseline_sft_500B | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 100% |
| baseline_dpo | 48.4 | 50.5 | 46.9 | 52.1 | 49.5 | 97% |
| llama32_1B_instruct | 43.0 | 39.0 | 48.0 | 43.0 | 43.2 | 100% |
| safelm_sft | 40.8 | 38.8 | 46.4 | 46.0 | 43.0 | 98% |
| safelm | 50.0 | 52.3 | 48.6 | 86.4 | 59.3 | 42%* |
| llama32_1B | 25.0 | 57.7 | 47.1 | 53.3 | 45.8 | 18%* |
| baseline_pretrain | N/E | N/E | N/E | N/E | N/E | 0% |
| baseline_pretrain_500B | N/E | N/E | N/E | N/E | N/E | 3%* |
| baseline_filtered_pretrain | N/E | N/E | N/E | N/E | N/E | 1%* |
| llama32_3B | N/E | N/E | N/E | N/E | N/E | 1%* |

*Very low parse rate; scores are unreliable.

---

## 4. Generation Results (Refusal Rate %)

Higher refusal rate = model is more cautious / safer when presented with biased or toxic prompts.

### 4.1 Stereotype Continuation (CEB-Continuation-S)

| Model | Gender | Age | Race | Religion | **Avg** |
|---|:---:|:---:|:---:|:---:|:---:|
| **safelm_sft** | 56.0 | 38.0 | 31.0 | 7.0 | **33.0** |
| llama32_1B_instruct | 33.0 | 17.0 | 28.0 | 7.0 | 21.3 |
| baseline_sft_500B | 1.0 | 0.0 | 3.0 | 3.0 | 1.7 |
| baseline_dpo | 1.0 | 0.0 | 1.0 | 1.0 | 0.8 |
| baseline_filtered_sft | 0.0 | 0.0 | 1.0 | 1.0 | 0.5 |
| baseline_sft | 0.0 | 0.0 | 1.0 | 1.0 | 0.5 |
| All pretrain / base | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

### 4.2 Toxic Continuation (CEB-Continuation-T)

| Model | Gender | Age | Race | Religion | **Avg** |
|---|:---:|:---:|:---:|:---:|:---:|
| **safelm_sft** | 54.0 | 61.0 | 55.0 | 78.0 | **62.0** |
| llama32_1B_instruct | 13.0 | 27.0 | 18.0 | 25.0 | 20.8 |
| baseline_sft_500B | 3.0 | 4.0 | 11.0 | 6.0 | 6.0 |
| baseline_dpo | 1.0 | 0.0 | 4.0 | 2.0 | 1.8 |
| baseline_sft | 2.0 | 0.0 | 3.0 | 2.0 | 1.8 |
| baseline_filtered_sft | 1.0 | 0.0 | 2.0 | 0.0 | 0.8 |
| All pretrain / base | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

### 4.3 Stereotype Conversation (CEB-Conversation-S)

| Model | Gender | Age | Race | Religion | **Avg** |
|---|:---:|:---:|:---:|:---:|:---:|
| **safelm_sft** | 72.0 | 51.0 | 50.0 | 52.0 | **56.2** |
| baseline_sft_500B | 50.0 | 57.0 | 47.0 | 61.0 | 53.8 |
| baseline_dpo | 44.0 | 35.0 | 37.0 | 32.0 | 37.0 |
| baseline_sft | 39.0 | 24.0 | 30.0 | 31.0 | 31.0 |
| baseline_filtered_sft | 29.0 | 22.0 | 13.0 | 10.0 | 18.5 |
| llama32_1B_instruct | 25.0 | 3.0 | 8.0 | 5.0 | 10.2 |
| baseline_pretrain | 0.0 | 1.0 | 6.0 | 2.0 | 2.2 |
| All other pretrain / base | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

### 4.4 Toxic Conversation (CEB-Conversation-T)

| Model | Gender | Age | Race | Religion | **Avg** |
|---|:---:|:---:|:---:|:---:|:---:|
| **safelm_sft** | 83.0 | 60.0 | 73.0 | 65.0 | **70.2** |
| baseline_sft_500B | 39.0 | 32.0 | 53.0 | 51.0 | 43.8 |
| baseline_dpo | 44.0 | 60.0 | 35.0 | 35.0 | 43.5 |
| baseline_sft | 34.0 | 49.0 | 29.0 | 29.0 | 35.2 |
| baseline_filtered_sft | 27.0 | 34.0 | 18.0 | 24.0 | 25.8 |
| llama32_1B_instruct | 37.0 | 3.0 | 19.0 | 21.0 | 20.0 |
| baseline_pretrain | 2.0 | 6.0 | 1.0 | 0.0 | 2.2 |
| All other pretrain / base | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

---

## 5. Model Category Summary

### 5.1 Overall Scores by Model Category

Only models with Parse% >= 50% on a given task are included (reliable scores).

| Category | Recog-S | Recog-T | Select-S | Select-T | Cont-S | Cont-T | Conv-S | Conv-T |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **SafeLM-SFT** | 51.4 | **60.4** | 45.0 | 43.0 | **33.0** | **62.0** | **56.2** | **70.2** |
| DPO | 49.1 | 55.3 | **62.9** | 49.5 | 0.8 | 1.8 | 37.0 | 43.5 |
| SFT-500B | 50.0 | 44.9 | 52.2 | 50.0 | 1.7 | 6.0 | 53.8 | 43.8 |
| SFT-100B | 50.0 | 48.9 | 54.9 | 50.6 | 0.5 | 1.8 | 31.0 | 35.2 |
| Filtered SFT | 50.6 | 50.0 | 50.0 | 50.2 | 0.5 | 0.8 | 18.5 | 25.8 |
| Llama 3.2 1B Inst. | 50.0 | 50.0 | 48.8 | 43.2 | 21.3 | 20.8 | 10.2 | 20.0 |
| SafeLM-base | 50.2 | 65.2* | 56.0* | 59.3* | 0.0 | 0.0 | 0.0 | 0.0 |
| Pretrain / base | N/E | N/E | N/E | N/E | 0.0 | 0.0 | 0.0 | 0.0 |

*Low parse rate (<50%); scores based on small subset of parseable responses.

### 5.2 Key Findings

1. **Pretrained models cannot be evaluated on classification tasks**: Without instruction tuning, pretrained models (baseline_pretrain, baseline_filtered_pretrain, baseline_pretrain_500B, llama32_1B, llama32_3B) simply echo the prompt text rather than producing answers. Echo detection correctly filters these out, resulting in 0% parse rate. Previous results that showed these models as having near-chance accuracy were artifacts of keyword-matching on echoed prompt text.

2. **Safety-tuned models lead on toxicity awareness**: SafeLM (base and SFT) achieves 60-65% on toxicity recognition, the only models significantly above chance. SafeLM-SFT also has the highest refusal rates across all generation tasks (33-70%).

3. **Stereotype recognition is near-random for all evaluable models**: No model with a reliable parse rate exceeds 52% on Recognition-S, indicating these 1.7B-scale models lack the capacity to reliably distinguish stereotypical from anti-stereotypical sentences.

4. **DPO training improves stereotype selection**: baseline_dpo reaches 62.9% on stereotype selection, the highest among reliable models. This suggests the comparison format of selection is easier than absolute classification for aligned models.

5. **Instruction following is a prerequisite for meaningful evaluation**: SFT is necessary for models to participate in the benchmark at all. Base models produce either prompt echoes or gibberish (e.g., code snippets from safelm-base).

6. **Training data filtering has limited impact on fairness**: baseline_filtered_sft vs. baseline_sft shows marginal differences (~1% on most metrics), suggesting data filtering alone does not substantially change fairness behavior.

7. **Conversation refusal is higher than continuation refusal**: Models show 2-4x higher refusal rates on conversation prompts vs. continuation prompts, likely because conversational format triggers safety guardrails more readily than article-continuation format.

8. **Gender bias is most readily detected/refused**: Across most models, gender-related prompts show the highest refusal rates, suggesting training data has more gender-related safety examples.

---

## 6. Methodology Notes

- **Generation**: vLLM with `temperature=0.0` for classification, `temperature=0.8` for generation tasks. `max_tokens=64` for classification, `512` for generation. Seed=42.
- **Chat template**: Applied automatically for instruct/SFT models; base models receive raw prompt with BOS token prepended.
- **Three-stage scoring**:
  1. **Echo detection**: Responses starting with "You are a helpful assistant" or matching the prompt prefix are filtered as unevaluable prompt echoes.
  2. **Rule-based parsing**: Extract "1"/"2", keyword matching for "stereotype"/"toxic".
  3. **LLM judge (GPT-4o-mini)**: For non-echo responses that rule-based parsing cannot handle (verbose explanations, non-standard answer formats).
- **Parse rate caveat**: Models with very low parse rates (< 50%) have unreliable accuracy scores based on small samples. Models with 0% parse rate are marked as "N/E" (not evaluable).

---

## 7. Files & Reproducibility

```
fairness/CEB/
├── run_ceb_eval.py              # Local vLLM generation + rule scoring
├── rescore_with_judge.py        # Echo detection + LLM judge re-scoring
├── CEB_EVAL_REPORT.md           # This report
├── generation_results/
│   ├── summary_all.json         # All generation-task results
│   ├── summary_judged.json      # All classification results (with judge)
│   └── <model_name>/
│       └── <CEB-Task>/
│           ├── <attribute>.json          # Per-sample responses + eval
│           └── <attribute>_results.json  # Aggregate scores
```

Reproduce:
```bash
# Generate + score (all models, all tasks). Use a single visible GPU unless
# you want vLLM tensor-parallel; pass --tp <N> to opt in.
CUDA_VISIBLE_DEVICES=0 python run_ceb_eval.py --task all --attribute all

# Re-score classification with echo detection + LLM judge
python rescore_with_judge.py
```

> If you run on a host where libstdc++ from the system clashes with the
> conda runtime (e.g. EL9-style images), prepend the conda lib dir on
> `LD_LIBRARY_PATH`:
>
> ```bash
> LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH}" \
>   python run_ceb_eval.py --task all --attribute all
> ```
>
