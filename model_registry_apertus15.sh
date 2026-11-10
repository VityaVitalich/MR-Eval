#!/bin/bash
# Apertus 1.5 8B — constitutional-SDPO pilot comparison (xccyn, 2026-11-09).
#
# Sourced by model_registry.sh (do NOT source on its own: relies on
# mr_eval_register_model and the MR_EVAL_MODEL_*_MAP arrays declared there).
# Name matches the model_registry*.sh glob that dashboard/build_data.py and
# slurm/summarize_post_train_evals.py read as TEXT, hence literal blocks with
# full paths (no loops, no variables).
#
# All three are swiss-ai Apertus-v1.5-8B checkpoints: model_type apertus1p5 =
# the 8B text LM plus bundled vision/audio tokenizers (text-only here). Chat
# template: <|system_start|>..<|user_start|>..<|assistant_start|> turns, the
# template injects its own default system prompt when none is given (our
# evals are user-turn only), thinking is off by default, assistant turns end
# with <|assistant_end|> (id 68; generation_config eos = [2, 68, 72]). The
# architecture only loads in the swiss-ai release image, so every suite for
# these aliases is submitted with `--env-kind apertus15`
# (container/apertus15.toml) and JBB_MAX_MODEL_LEN=8192 (262k context model).
# No --chat-template / --eos-token overrides: the repo template is the
# training template. Not runnable for this architecture: pez, abliteration,
# the ft_* chains (HarmBench / train images do not know apertus1p5).
#
#   A  apertus15_8b_dpo          swiss-ai/Apertus-v1.5-8B-DPO — the SDPO starting
#                                 checkpoint, no local training (HF snapshot
#                                 b35d0989 in xccyn's model-metadata cache)
#   B  apertus15_8b_csdpo_step2  xccyn's constitutional SDPO pilot: initialised
#                                 from A, Gretel prompts + Charter principles +
#                                 Qwen-generated feedback, 2 optimizer steps (one
#                                 with non-zero lr) — an engineering test; the
#                                 main comparison is B vs A. Her export
#                                 (.../nov09-recovery/merged/B-step2) is ONE
#                                 model.safetensors; the vLLM fork loads Apertus
#                                 1.5 only from model-apertus-model-*.safetensors
#                                 + model-vision_tokenizer-model / model-wavtokenizer-
#                                 model.safetensors (apertus_mm.py
#                                 allow_patterns_overrides), so the registry points
#                                 at a byte-exact re-layout in vvmoskvoretskii's
#                                 hf_models (apertus15_smoke/split_apertus_export.py,
#                                 2026-11-10; configs/tokenizer copied verbatim).
#   C  apertus15_8b_release      swiss-ai/Apertus-v1.5-8B — the authors' released
#                                 SDPO model (external reference, not a matched run)

mr_eval_register_model \
  --alias apertus15_8b_dpo \
  --pretrained /capstor/store/cscs/swissai/ab023/xccyn/spsd/self-distillation-pretraining/local/experiments/apertus-reproduction-20261022/coordinator/model-metadata-cache/models--swiss-ai--Apertus-v1.5-8B-DPO/snapshots/b35d098959826a4c0709593a1b78c219f5b4b864 \
  --description "Apertus 1.5 8B DPO (swiss-ai/Apertus-v1.5-8B-DPO): the SDPO starting checkpoint, no local training; Apertus chat template, text-only eval (A of the constitutional-SDPO pilot comparison)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias apertus15_8b_csdpo_step2 \
  --pretrained /capstor/store/cscs/swissai/infra01/users/vvmoskvoretskii/hf_models/apertus15_8b_csdpo_step2 \
  --description "Apertus 1.5 8B constitutional-SDPO pilot (xccyn): init from apertus15_8b_dpo, Gretel prompts + Charter principles + Qwen feedback, 2 optimizer steps (1 non-zero lr), B-step2 merged export re-laid out into the official per-component safetensors files (byte-exact, see README.txt there); Apertus chat template, text-only eval (B, compare against A)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias apertus15_8b_release \
  --pretrained /capstor/store/cscs/swissai/infra01/hf_models/models/swiss-ai/Apertus-v1.5-8B \
  --description "Apertus 1.5 8B official release (swiss-ai/Apertus-v1.5-8B): the authors' SDPO model, external reference for the pilot; Apertus chat template, text-only eval (C)" \
  --jbb-config generic_instruct
