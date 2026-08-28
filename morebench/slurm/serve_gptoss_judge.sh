#!/bin/bash
# gpt-oss-120b judge serve for morebench Stage 2 (Swiss-AI gateway / OpenTela).
#
# Self-contained sbatch script (gemma-master pattern) — submit DIRECTLY:
#   sbatch slurm/serve_gptoss_judge.sh                                   # debug, 90 min
#   sbatch --partition=normal --time=06:00:00 slurm/serve_gptoss_judge.sh  # long window*
# Serves vLLM tp4 on one GH200 node as  vvmoskvoretskii/openai/gpt-oss-120b
# (matches morebench conf judge.model). Gateway-ready in ~13 min; throughput
# ~1 judged criterion/s at client concurrency 48 (one 150-scenario theory
# model ~= 70 min). Cancel with scancel when judging is done.
#
# *The OpenTela expires_at label below is +5400s (90 min) — RAISE IT to match
#  a longer --time or the mesh may drop the provider while the job still runs.
#
# Why not `sml preconfigured/advanced` (2026-08-27): the sml-rendered launches
# hang for gpt-oss — engines block on write() right after weight load (both
# sglang and vLLM; the new sidecar stops draining a chatty subprocess), and
# the current sglang image wedges even when quiet. This script bakes in the
# three required fixes:
#   1. OpenTela binary at /opentelabin/prod/ (moved from /ocfbin/prod/);
#   2. TQDM_DISABLE=1 + VLLM_LOGGING_LEVEL=WARNING (quiet engine — see above);
#   3. openai_harmony tiktoken vocab served OFFLINE: ~/tiktoken_cache
#      (sha1-named file, generate once via `pip install openai-harmony` +
#      load_harmony_encoding on a machine with internet) bind-mounted into the
#      container ($HOME is NOT visible inside the vllm image).
#SBATCH --job-name=sml_gptoss_judge_dbg
#SBATCH --account=infra01
#SBATCH --time=01:30:00
#SBATCH --exclusive
#SBATCH --nodes=1
#SBATCH --partition=debug
#SBATCH --output=logs/%j/log.out
#SBATCH --error=logs/%j/log.out
# shellcheck shell=bash

set -euo pipefail

critical_pids=()
vmagent_pid=""

# Self-extract rank scripts: this master.sh was submitted standalone
# (no sibling files), so we materialise the rank scripts under HOME
# (shared FS, visible to all compute nodes) at job start time. The
# single-quoted heredoc keeps each body literal.

RANKS_DIR="$HOME/.sml/job-${SLURM_JOB_ID}"

mkdir -p "$RANKS_DIR"

cat > "$RANKS_DIR/head.sh" <<'__SML_HEAD_EOF__'
#!/bin/bash
# shellcheck disable=SC2046,SC2086
set -ex

export RAY_CGRAPH_get_timeout=1800
export no_proxy="0.0.0.0,$no_proxy"
export NO_PROXY="0.0.0.0,$NO_PROXY"

# gpt-oss: openai_harmony needs the tiktoken vocab offline (pre-cached on $HOME)
export TIKTOKEN_RS_CACHE_DIR=/tiktoken_cache   # bind-mounted; $HOME is not visible in the container

# keep the engine quiet: the OpenTela sidecar has been observed not draining a
# chatty subprocess (engines block on write() post-weight-load) — no tqdm bars,
# warnings only.
export TQDM_DISABLE=1
export VLLM_LOGGING_LEVEL=WARNING

# shellcheck disable=SC2034
replica_head_ip="$1"

$OCF_BIN start \
    --bootstrap.addr "/ip4/148.187.108.178/tcp/43905/p2p/QmbUKJkCfotDzbFE5uoTsXD4GRyPHjzZC1f2yAGLoeBMn9" \
    --service.name llm \
    --service.port 8080 \
    --label launched_by=$USER \
    --label slurm_job_id=$SLURM_JOB_ID \
    --label slurm_partition=${SLURM_JOB_PARTITION:-unknown} \
    --label worker_group_id=$SLURM_JOB_ID \
    --label framework=vllm \
    --label served_model_name=vvmoskvoretskii/openai/gpt-oss-120b \
    --label 'framework_args=--port 8080 --model /capstor/store/cscs/swissai/infra01/hf_models/models/openai/gpt-oss-120b --served-model-name vvmoskvoretskii/openai/gpt-oss-120b --host 0.0.0.0 --tensor-parallel-size 4' \
    --label started_at=$(date -u +%FT%TZ) \
    --label expires_at=$(date -u -d "+5400 seconds" +%FT%TZ) \
    --subprocess "python3 -m vllm.entrypoints.openai.api_server --port 8080 --model /capstor/store/cscs/swissai/infra01/hf_models/models/openai/gpt-oss-120b --served-model-name vvmoskvoretskii/openai/gpt-oss-120b --host 0.0.0.0 --tensor-parallel-size 4"
__SML_HEAD_EOF__

chmod +x "$RANKS_DIR/head.sh"

curl -sf -X POST "https://sml-dev.swissai.svc.cscs.ch/launches" \
    -H "Content-Type: application/json" \
    -d '{"user": "'"${SLURM_JOB_USER}"'", "job_id": "'"${SLURM_JOB_ID}"'", "slurm_nodes": '"${SLURM_NNODES}"', "slurm_job_name": "'"${SLURM_JOB_NAME}"'", "slurm_partition": "'"${SLURM_JOB_PARTITION}"'", "slurm_time": "01:30:00", "slurm_account": "'"${SLURM_JOB_ACCOUNT}"'", "slurm_environment": "src/swiss_ai_model_launch/assets/envs/vllm.toml", "interactive": false, "serving_framework": "vllm", "framework_args": "--port 8080 --model /capstor/store/cscs/swissai/infra01/hf_models/models/openai/gpt-oss-120b --served-model-name vvmoskvoretskii/openai/gpt-oss-120b --host 0.0.0.0 --tensor-parallel-size 4", "pre_launch_cmds": "", "model_name": "vvmoskvoretskii/openai/gpt-oss-120b", "replicas": 1, "nodes_per_replica": 1, "framework_port": 8080, "use_router": false, "router_environment": "src/swiss_ai_model_launch/assets/envs/vllm.toml", "router_port": 30000, "router_args": "", "ocf_enabled": true, "ocf_bootstrap_addr": "/ip4/148.187.108.178/tcp/43905/p2p/QmbUKJkCfotDzbFE5uoTsXD4GRyPHjzZC1f2yAGLoeBMn9", "ocf_service_name": "llm", "ocf_service_port": 8080, "model_launch_version": "26.5.0a1"}' || true

unset SLURM_CPU_BIND SLURM_CPU_BIND_TYPE SLURM_CPU_BIND_LIST SLURM_CPU_BIND_VERBOSE

ARCH=$(uname -m)
if [[ "$ARCH" == "aarch64" ]]; then
    echo "Running on ARM64 (aarch64)"
    export SP_NCCL_SO_PATH=/usr/lib/aarch64-linux-gnu/
    export OCF_BIN=/opentelabin/prod/otela-arm64
    metrics_agent_bin="/capstor/store/cscs/swissai/infra01/ocf-share/vmagent-arm64"
    dcgm_exporter_bin="/capstor/store/cscs/swissai/infra01/ocf-share/dcgm-exporter-arm64"
elif [[ "$ARCH" == "x86_64" ]]; then
    echo "Running on x86_64"
    export SP_NCCL_SO_PATH=/usr/lib/x86_64-linux-gnu/
    export OCF_BIN=/opentelabin/prod/otela-amd64
    metrics_agent_bin="/capstor/store/cscs/swissai/infra01/ocf-share/vmagent-amd64"
    dcgm_exporter_bin="/capstor/store/cscs/swissai/infra01/ocf-share/dcgm-exporter-amd64"
else
    echo "Unknown architecture: $ARCH" >&2
    exit 1
fi

mapfile -t nodes < <(scontrol show hostnames "$SLURM_NODELIST")
TOTAL_NODES=${#nodes[@]}

echo "Total nodes allocated: $TOTAL_NODES"
for i in "${!nodes[@]}"; do
    echo "Node $i: ${nodes[$i]}"
done

# ── replica 0 head IP ─────────────────────────────────────────────
replica_0_head_node=${nodes[0]}
replica_0_head_ip=$(srun --nodes=1 --ntasks=1 -w "$replica_0_head_node" hostname -i)
if [[ -z "$replica_0_head_ip" ]]; then
    echo "Error: Could not retrieve IP for replica 0 host $replica_0_head_node" >&2
    exit 1
fi
echo "Replica 0 head IP: $replica_0_head_ip"

echo "All replica URLs: http://$replica_0_head_ip:8080"  # NOSONAR

# replica 0, rank 0 (head)
srun --nodes=1 --ntasks=1 --nodelist="${nodes[0]}" \
    --container-writable \
    --container-mounts="$RANKS_DIR:$RANKS_DIR,/users/vvmoskvoretskii/tiktoken_cache:/tiktoken_cache" \
    --environment="/users/vvmoskvoretskii/model-launch/src/swiss_ai_model_launch/assets/envs/vllm.toml" \
    bash "$RANKS_DIR/head.sh" "$replica_0_head_ip" &
critical_pids+=($!)

# vmagent runs on the batch node; pyxis containers share the host network
# namespace so the framework API server is reachable at localhost:8080.
# vmagent is non-critical: disowned so it's not in `wait -n`'s scope, and
# the EXIT trap in the footer kills it when master.sh terminates so the
# allocation can be released as soon as the framework process is gone.
if [[ -x "$metrics_agent_bin" ]]; then
    if [[ -e /dev/nvidia0 && -x "$dcgm_exporter_bin" ]]; then
        "$dcgm_exporter_bin" \
            --address 0.0.0.0:9400 \
            -f /capstor/store/cscs/swissai/infra01/ocf-share/default-counters.csv \
            > "/tmp/dcgm-exporter-${SLURM_JOB_ID}.log" 2>&1 &
        disown $!
    else
        echo "dcgm-exporter: no NVIDIA GPU or binary not found, skipping" >&2
    fi
    "$metrics_agent_bin" \
        -promscrape.config=/capstor/store/cscs/swissai/infra01/ocf-share/vmagent-scrape.yaml \
        -remoteWrite.url="https://prometheus-dev.swissai.svc.cscs.ch/api/v1/write" \
        -remoteWrite.label="slurm_job_id=${SLURM_JOB_ID}" \
        -remoteWrite.label="model=vvmoskvoretskii/openai/gpt-oss-120b" \
        -remoteWrite.label="framework=vllm" \
        -remoteWrite.label="user=${SLURM_JOB_USER}" \
        -remoteWrite.label="node=$(hostname)" \
        "-remoteWrite.tmpDataPath=/tmp/vmagent-data-${SLURM_JOB_ID}" \
        > "/tmp/vmagent-${SLURM_JOB_ID}.log" 2>&1 &
    vmagent_pid=$!
    disown "$vmagent_pid"
else
    echo "metrics: $metrics_agent_bin not found, skipping push" >&2
fi

echo
echo "To connect to the host node:"
echo "srun --jobid $SLURM_JOB_ID -w ${nodes[0]} --overlap --pty bash"

echo
echo "Make sure to cancel the job at the end:"
echo "scancel $SLURM_JOB_ID"

cleanup() {
    if [[ -n "$vmagent_pid" ]]; then
        kill "$vmagent_pid" 2>/dev/null || true
    fi
    if (( ${#critical_pids[@]} > 0 )); then
        kill "${critical_pids[@]}" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

rc=0
wait -n || rc=$?
echo "Master finished at $(date) with code $rc"
exit "$rc"
