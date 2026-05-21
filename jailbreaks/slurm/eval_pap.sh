#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
# Slurm apptainer spec: use the MR-Eval harmbench image (CUDA + vLLM-friendly env).
# Edit the absolute path if your clone lives elsewhere. Slurm does not expand $vars in #SBATCH.
#SBATCH --environment=/users/yyiderigun/workspace/MR-Eval/container/harmbench.toml
#SBATCH --output=logs/jailbreaks-pap-%j.out
#SBATCH --error=logs/jailbreaks-pap-%j.err
#SBATCH --no-requeue

# Persuasive Adversarial Prompt (PAP) evaluation on the vendored AdvBench JSONL subset.
# Prefer this job over login-node conda: the container supplies CUDA libs + matching torch/vLLM.
#
# Usage (run sbatch from jailbreaks/):
#   sbatch slurm/eval_pap.sh
#   sbatch slurm/eval_pap.sh meta-llama/Llama-3.2-1B-Instruct keyword
#   sbatch slurm/eval_pap.sh alpindale/Llama-3.2-1B-Instruct llm data/persuasive_jailbreak/advbench_pap_k2_seed42.jsonl

MODEL=${1:-"alpindale/Llama-3.2-1B-Instruct"}
JUDGE=${2:-llm}
PAP_FILE=${3:-}

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from jailbreaks/}"
cd "$EVAL_DIR"

[ -f ~/.env ] && source ~/.env

mkdir -p "$EVAL_DIR/logs"

nvidia-smi

echo "START TIME: $(date)"
echo "Model:    $MODEL"
echo "Judge:    $JUDGE"
echo "PAP file: ${PAP_FILE:-default from conf/pap.yaml}"
start=$(date +%s)

cmd=(
  python run_pap_eval.py
  model.pretrained="$MODEL"
  judge_mode="$JUDGE"
)

if [ -n "$PAP_FILE" ]; then
  cmd+=(pap_file="$PAP_FILE")
fi

"${cmd[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
