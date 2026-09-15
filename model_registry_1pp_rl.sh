#!/bin/bash
# 1PP GRPO (RL) sub-registry — the GSM8K reinforcement-learning trajectories.
#
# Sourced by model_registry.sh (after model_registry_1pp.sh). Do NOT source on
# its own: it relies on mr_eval_register_model and the MR_EVAL_MODEL_*_MAP
# arrays the main registry declares. Name matches the model_registry*.sh glob
# that dashboard/build_data.py and slurm/summarize_post_train_evals.py use.
#
# Provenance (mr-eval-rl, verl 0.9.0.dev0, GRPO, 2026-09-14):
#
#   parents     the three 1pp_1p7b_{asst,ua,raw}_sft aliases above. RL starts
#               from the SFT checkpoint, so every alias here has an exact
#               pre-RL counterpart in model_registry_1pp.sh — that is the
#               comparison these were made for.
#   task        GSM8K, rule-based correctness reward (verl's own scorer,
#               unmodified), rollout.n=16, train_batch_size=256 prompts,
#               ppo_mini_batch_size=128 prompts, ppo_epochs=3, lr 1e-6 flat,
#               KL kept (nothing dropped from the algorithm).
#   trajectory  100 steps, checkpointed every 10 -> s10..s100 per condition.
#               GSM8K pass@1 over the run: asst 0.011->0.039, ua 0.010->0.041,
#               raw 0.008->0.037 (validation, rollout.n=16).
#
# CAVEAT that governs how these may be read: a config-identical repeat of the
# asst run landed at 0.055 pass@1 vs 0.039 at step 100 — a seed gap LARGER than
# the entire asst/ua/raw spread (0.037-0.041). Comparing a GRPO alias against
# its own SFT parent is sound; ranking asst vs ua vs raw on these three runs is
# reading noise. One seed each.
#
# Why absolute paths and not HF repo ids: the trajectory is also published at
# VityaVitalich/1pp-1.7b-<cond>-sft-grpo-gsm8k with one `step-<N>` branch per
# checkpoint, but mr_eval_register_model has no --revision and the eval loaders
# never pass one, so a repo id can only ever reach `main` (= step 100). The
# local dirs are byte-identical in content to those branches: built by
# scratchpad/materialize_rl_ckpts.py, which casts verl's F32 master weights to
# the bf16 that config.json already declares and restores the four tokenizer
# files verl drops (added_tokens.json, merges.txt, special_tokens_map.json,
# vocab.json) from the SFT parent's snapshot. Without those four, use_fast=False
# cannot load the tokenizer at all.
#
# EOS: the exports carry the parent's generation_config (eos_token_id [2, 0] =
# <|im_end|>, <|endoftext|>) and the parent's chat_template.jinja, so these need
# NO --eos-token override — same as the *_sft aliases, unlike the *_base ones.
#
# Alias scheme: 1pp_1p7b_<condition>_grpo_s<step>. Keeps the 1pp_ prefix so
# mr_eval_model_cohort classifies them as the 1pp cohort, not legacy.

_MR_EVAL_1PP_RL_ROOT=/capstor/store/cscs/swissai/ab023/vvmoskvoretskii/rl/eval_ckpts

for _cond in asst ua raw; do
  case "$_cond" in
    asst) _desc="asst pretraining (docs rewritten as conversations, loss on assistant turns only)" ;;
    ua)   _desc="ua pretraining (docs rewritten as conversations, loss on user + assistant turns)" ;;
    raw)  _desc="raw pretraining (original documents, plain-text control)" ;;
  esac
  for _step in 10 20 30 40 50 60 70 80 90 100; do
    mr_eval_register_model \
      --alias "1pp_1p7b_${_cond}_grpo_s${_step}" \
      --pretrained "${_MR_EVAL_1PP_RL_ROOT}/1pp_1p7b_${_cond}_grpo_s${_step}" \
      --description "1PP 1.7B, ${_desc}, + SFT, + GRPO on GSM8K (verl, rollout.n=16, ppo_epochs=3, lr 1e-6, KL on), global step ${_step} of 100; pre-RL parent is 1pp_1p7b_${_cond}_sft; ChatML, no system prompt" \
      --jbb-config generic_instruct
  done
done
unset _cond _step _desc
