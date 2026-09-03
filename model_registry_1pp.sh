#!/bin/bash
# 1PP (One Persona Pretraining) sub-registry.
#
# Sourced by model_registry.sh (last thing it does). Do NOT source this file
# on its own: it relies on mr_eval_register_model and the MR_EVAL_MODEL_*_MAP
# arrays the main registry declares, and every consumer keeps sourcing
# model_registry.sh only. It is a separate file because 1PP is a separate
# model CLASS — not another pbsftmix / chempileedu / epe variant — that shares
# the eval suite (instruct track: eval_sft + the post-train safety matrix) but
# none of the lineage. Python-side registry readers (dashboard/build_data.py,
# slurm/summarize_post_train_evals.py) glob model_registry*.sh, so a further
# sub-registry only has to follow that name pattern + be sourced below.
#
# Source: https://huggingface.co/collections/Raghav-Singhal/1pp (18 repos,
# registered 2026-09-03). Model-card facts that matter for evaluation:
#
#   sizes       0.5b (0.58B) / 1b (0.98B) / 1.7b (1.66B). Llama arch, SmolLM2
#               vocab (49,152) + <|pad|>, seq 4096, Muon optimizer. Same 47.8M
#               source documents in the same order for every run.
#   conditions  asst = docs rewritten as conversations, loss on assistant turns
#               ua   = rewritten conversations, loss on user + assistant turns
#               raw  = original documents (plain-text control)
#   stages      -base = the pretraining checkpoint. For asst/ua the pretraining
#                       corpus IS chat-formatted, so "base" is already an
#                       assistant: 1pp_*_{asst,ua}_base run on the INSTRUCT
#                       track (eval_sft + submit_posttrain_evals.sh). The raw
#                       control's -base is a regular plain-text pretrained model
#                       (Viktor, 2026-09-03: "raw base = regular pretrained
#                       model; asst/ua = like sft"), so 1pp_*_raw_base run on
#                       the BASE track (submit_base_evals.sh: eval_base +
#                       safety_base), no chat template, jbb generic_base.
#               -sft  = -base + 1 epoch SFT: jkminder/model-raising-pb-100k-3c-mt-sft
#                       + dlab-spp/sp-sft-normal-300k + 30k of sp-sft-safety-180k.
#   template    ChatML WITHOUT a system turn (the models never saw one), baked
#               into each repo's chat_template.jinja; no additional_chat_templates/
#               => no --chat-template override (tokenizer default is correct).
#   EOS         -sft repos declare generation_config eos_token_id [2, 0]
#               (<|im_end|>, <|endoftext|>) so vLLM / HF generate stop at the end
#               of the assistant turn. -base repos declare only 0 (<|endoftext|>)
#               and their tokenizer eos is <|endoftext|> too, i.e. NOTHING in
#               the repo metadata stops generation at <|im_end|> — every other
#               SmolLM-family model in the registry has eos = <|im_end|>.
#               Verified 2026-09-03 (0.5b asst-base, greedy, transformers): a
#               clean answer, <|im_end|>, then run-on pseudo-turns for the rest
#               of the token budget. Hence --eos-token "<|im_end|>" on the six
#               {asst,ua}_base aliases: the job-wide tokenizer hook sets eos_token to it,
#               so vLLM / HF generate / lm-eval stop at the end of the turn.
#               Drop the flag once the repos ship eos_token_id [2, 0].
#               raw-base never emits <|im_end|> at all (plain-text base model:
#               it echoes the prompt and continues as a document) — one more
#               reason it lives on the base track, with no override.
#   jbb         generic_instruct for the instruct-track aliases (chat template,
#               bf16, no system prompt); generic_base for 1pp_*_raw_base.
#
# Alias scheme: 1pp_<size>_<condition>_<stage>, size 0.5b -> 0p5b, 1.7b -> 1p7b
# (repo convention, cf. smollm_1p7b_sft). Tokens mirror the HF repo names so an
# alias maps back to its repo by eye.

### 1PP 0.5B (0.58B params)

mr_eval_register_model \
  --alias 1pp_0p5b_asst_base \
  --pretrained Raghav-Singhal/1pp-0.5b-asst-base \
  --description "1PP 0.5B, asst pretraining (docs rewritten as conversations, loss on assistant turns only), pretrain-only checkpoint (HF name says 'base' but for asst/ua the pretraining corpus is ChatML, so it is already an assistant -> INSTRUCT track); ChatML, no system prompt" \
  --jbb-config generic_instruct \
  --eos-token "<|im_end|>"

mr_eval_register_model \
  --alias 1pp_0p5b_asst_sft \
  --pretrained Raghav-Singhal/1pp-0.5b-asst-sft \
  --description "1PP 0.5B, asst pretraining (docs rewritten as conversations, loss on assistant turns only), + SFT (pb-100k-3c-mt + sp-sft-normal-300k + 30k sp-sft-safety, 1 epoch, Muon); ChatML, no system prompt" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias 1pp_0p5b_ua_base \
  --pretrained Raghav-Singhal/1pp-0.5b-ua-base \
  --description "1PP 0.5B, ua pretraining (docs rewritten as conversations, loss on user + assistant turns), pretrain-only checkpoint (HF name says 'base' but for asst/ua the pretraining corpus is ChatML, so it is already an assistant -> INSTRUCT track); ChatML, no system prompt" \
  --jbb-config generic_instruct \
  --eos-token "<|im_end|>"

mr_eval_register_model \
  --alias 1pp_0p5b_ua_sft \
  --pretrained Raghav-Singhal/1pp-0.5b-ua-sft \
  --description "1PP 0.5B, ua pretraining (docs rewritten as conversations, loss on user + assistant turns), + SFT (pb-100k-3c-mt + sp-sft-normal-300k + 30k sp-sft-safety, 1 epoch, Muon); ChatML, no system prompt" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias 1pp_0p5b_raw_base \
  --pretrained Raghav-Singhal/1pp-0.5b-raw-base \
  --description "1PP 0.5B, raw pretraining (original documents, plain-text control), pretrain-only checkpoint = a regular plain-text BASE model (Viktor, 2026-09-03) -> BASE track (eval_base + safety_base), no chat template" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias 1pp_0p5b_raw_sft \
  --pretrained Raghav-Singhal/1pp-0.5b-raw-sft \
  --description "1PP 0.5B, raw pretraining (original documents, plain-text control), + SFT (pb-100k-3c-mt + sp-sft-normal-300k + 30k sp-sft-safety, 1 epoch, Muon); ChatML, no system prompt" \
  --jbb-config generic_instruct

### 1PP 1B (0.98B params)

mr_eval_register_model \
  --alias 1pp_1b_asst_base \
  --pretrained Raghav-Singhal/1pp-1b-asst-base \
  --description "1PP 1B, asst pretraining (docs rewritten as conversations, loss on assistant turns only), pretrain-only checkpoint (HF name says 'base' but for asst/ua the pretraining corpus is ChatML, so it is already an assistant -> INSTRUCT track); ChatML, no system prompt" \
  --jbb-config generic_instruct \
  --eos-token "<|im_end|>"

mr_eval_register_model \
  --alias 1pp_1b_asst_sft \
  --pretrained Raghav-Singhal/1pp-1b-asst-sft \
  --description "1PP 1B, asst pretraining (docs rewritten as conversations, loss on assistant turns only), + SFT (pb-100k-3c-mt + sp-sft-normal-300k + 30k sp-sft-safety, 1 epoch, Muon); ChatML, no system prompt" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias 1pp_1b_ua_base \
  --pretrained Raghav-Singhal/1pp-1b-ua-base \
  --description "1PP 1B, ua pretraining (docs rewritten as conversations, loss on user + assistant turns), pretrain-only checkpoint (HF name says 'base' but for asst/ua the pretraining corpus is ChatML, so it is already an assistant -> INSTRUCT track); ChatML, no system prompt" \
  --jbb-config generic_instruct \
  --eos-token "<|im_end|>"

mr_eval_register_model \
  --alias 1pp_1b_ua_sft \
  --pretrained Raghav-Singhal/1pp-1b-ua-sft \
  --description "1PP 1B, ua pretraining (docs rewritten as conversations, loss on user + assistant turns), + SFT (pb-100k-3c-mt + sp-sft-normal-300k + 30k sp-sft-safety, 1 epoch, Muon); ChatML, no system prompt" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias 1pp_1b_raw_base \
  --pretrained Raghav-Singhal/1pp-1b-raw-base \
  --description "1PP 1B, raw pretraining (original documents, plain-text control), pretrain-only checkpoint = a regular plain-text BASE model (Viktor, 2026-09-03) -> BASE track (eval_base + safety_base), no chat template" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias 1pp_1b_raw_sft \
  --pretrained Raghav-Singhal/1pp-1b-raw-sft \
  --description "1PP 1B, raw pretraining (original documents, plain-text control), + SFT (pb-100k-3c-mt + sp-sft-normal-300k + 30k sp-sft-safety, 1 epoch, Muon); ChatML, no system prompt" \
  --jbb-config generic_instruct

### 1PP 1.7B (1.66B params)

mr_eval_register_model \
  --alias 1pp_1p7b_asst_base \
  --pretrained Raghav-Singhal/1pp-1.7b-asst-base \
  --description "1PP 1.7B, asst pretraining (docs rewritten as conversations, loss on assistant turns only), pretrain-only checkpoint (HF name says 'base' but for asst/ua the pretraining corpus is ChatML, so it is already an assistant -> INSTRUCT track); ChatML, no system prompt" \
  --jbb-config generic_instruct \
  --eos-token "<|im_end|>"

mr_eval_register_model \
  --alias 1pp_1p7b_asst_sft \
  --pretrained Raghav-Singhal/1pp-1.7b-asst-sft \
  --description "1PP 1.7B, asst pretraining (docs rewritten as conversations, loss on assistant turns only), + SFT (pb-100k-3c-mt + sp-sft-normal-300k + 30k sp-sft-safety, 1 epoch, Muon); ChatML, no system prompt" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias 1pp_1p7b_ua_base \
  --pretrained Raghav-Singhal/1pp-1.7b-ua-base \
  --description "1PP 1.7B, ua pretraining (docs rewritten as conversations, loss on user + assistant turns), pretrain-only checkpoint (HF name says 'base' but for asst/ua the pretraining corpus is ChatML, so it is already an assistant -> INSTRUCT track); ChatML, no system prompt" \
  --jbb-config generic_instruct \
  --eos-token "<|im_end|>"

mr_eval_register_model \
  --alias 1pp_1p7b_ua_sft \
  --pretrained Raghav-Singhal/1pp-1.7b-ua-sft \
  --description "1PP 1.7B, ua pretraining (docs rewritten as conversations, loss on user + assistant turns), + SFT (pb-100k-3c-mt + sp-sft-normal-300k + 30k sp-sft-safety, 1 epoch, Muon); ChatML, no system prompt" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias 1pp_1p7b_raw_base \
  --pretrained Raghav-Singhal/1pp-1.7b-raw-base \
  --description "1PP 1.7B, raw pretraining (original documents, plain-text control), pretrain-only checkpoint = a regular plain-text BASE model (Viktor, 2026-09-03) -> BASE track (eval_base + safety_base), no chat template" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias 1pp_1p7b_raw_sft \
  --pretrained Raghav-Singhal/1pp-1.7b-raw-sft \
  --description "1PP 1.7B, raw pretraining (original documents, plain-text control), + SFT (pb-100k-3c-mt + sp-sft-normal-300k + 30k sp-sft-safety, 1 epoch, Muon); ChatML, no system prompt" \
  --jbb-config generic_instruct
