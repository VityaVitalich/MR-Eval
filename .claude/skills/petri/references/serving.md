# Serving the target for a native Petri run

The proven path serves the target on the **CSCS Swiss AI inference gateway** with
`sml` (the `model-launch` tool), the same way we host gemma. Once up, the target
is an OpenAI-compatible model reachable **from the Mac** at:

- **Base URL:** `https://api.swissai.svc.cscs.ch/v1`  (this is the API host; the
  `serving.swissai.svc.cscs.ch` you log into for keys is just the portal website)
- **Model id:** `vvmoskvoretskii/pbsftmix/cite-normal-3b-s10`  (the gateway requires a
  3-part `<namespace>/<org>/<name>` id; sml prepends the `vvmoskvoretskii/` namespace —
  see the gotcha in step 3)
- **Auth:** the **Swiss AI Research API key** as a bearer token.

Auditor + judge are Claude Code subagents on the Mac; only the target touches the
cluster, so the compute node needs no internet.

## What's fixed on the cluster (from the setup run, 2026-09-02)
- Weights: `/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/hf_models/pbsftmix-cite-safety10-nosys-normal-3b`
  (HF `Raghav-Singhal/pbsftmix-cite-safety10-nosys-normal-3b`, alias `pbsftmix_cite_normal_3b_s10`, public, ~6 GB).
- Chat template: `/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/petri-serve/epe-template-nosys.jinja`
  (identical to `assets/epe-template-nosys.jinja` in this skill; verified byte-for-byte
  against `~/pbmt-chat-eval/pbmt_serve.py:build_prompt`). **Must live under `/capstor`**
  — the vLLM container mounts `/capstor` + `/iopsstor` but NOT `/users` (home), so a
  jinja in your home dir is invisible inside the container and vLLM dies with
  "chat template … doesn't exist". Same applies to the weights (already on `/capstor`).
- `sml` lives in `~/model-launch/.venv` (`cd ~/model-launch && source .venv/bin/activate`).
- Downloads/parity use conda base (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate base`),
  NOT the login python3 (that's a broken 3.6).

## Step 1 — stage the weights on the cluster (once per checkpoint)
Compute nodes have no internet, so download on the login node to a `--local-dir`:
```bash
ssh clariden
source ~/miniconda3/etc/profile.d/conda.sh && conda activate base
DEST=/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/hf_models/<hf-repo-basename>
HF_HUB_ENABLE_HF_TRANSFER=1 hf download <org>/<hf-repo> --local-dir "$DEST"
```

## Step 2 — the chat template (load-bearing; get it wrong and the audit is garbage)
The checkpoint's bundled `chat_template.jinja` is WRONG. Use
`assets/epe-template-nosys.jinja` from this skill: no system turn, user turns are
`<|im_start|>user\n…<|im_end|>\n`, assistant turns/header use `<|im_start|><assistant>`
(**angle brackets, no newline**), tokenized with **no BOS**. Copy it to clariden and
verify parity before launching (needs `jinja2`; `pip install -q jinja2` into conda
base if missing — it's pure-python and harmless):
```bash
# copy to a /capstor path (NOT home — the container can't see /users):
scp .claude/skills/petri/assets/epe-template-nosys.jinja \
  clariden:/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/petri-serve/
# on clariden, conda base: render it and assert it equals build_prompt() for
# single-turn, multi-turn, and that a system message raises. (See the setup
# transcript / ~/petri-serve/verify_jinja.py.) Must print ALL_PARITY: True.
```

## Step 3 — launch with `sml advanced`
```bash
ssh clariden 'cd ~/model-launch && source .venv/bin/activate && sml advanced \
  --partition normal \
  --account ab023 \
  --framework vllm \
  --environment src/swiss_ai_model_launch/assets/envs/vllm.toml \
  --time 04:00:00 \
  --no-tui \
  --framework-args "--model /capstor/store/cscs/swissai/infra01/vvmoskvoretskii/hf_models/pbsftmix-cite-safety10-nosys-normal-3b \
    --served-model-name pbsftmix/cite-normal-3b-s10 \
    --chat-template /capstor/store/cscs/swissai/infra01/vvmoskvoretskii/petri-serve/epe-template-nosys.jinja \
    --max-model-len 2048 \
    --host 0.0.0.0"'
```
Gotchas learned the hard way:
- **Served name → 3-part gateway id.** The gateway ONLY registers ids shaped
  `<namespace>/<org>/<name>` (e.g. `mzueri/google/gemma-3-27b-it`); a 2-part id
  silently never appears in `/v1/models`. sml prepends your `vvmoskvoretskii/`
  namespace, so pass an **`<org>/<name>`** value (here `pbsftmix/cite-normal-3b-s10`)
  → final `vvmoskvoretskii/pbsftmix/cite-normal-3b-s10`. Don't include your own
  namespace (that doubles it to `vvmoskvoretskii/vvmoskvoretskii/…`), and don't pass a
  bare 1-part name (that yields an unregisterable 2-part id). Render-and-check first
  with `--output-script <dir>` (writes `master.sh`+`head.sh`, submits nothing) and
  grep `--served-model-name` in `head.sh`.
- **`--account ab023`** (our project account). `--partition normal`; the job takes a
  whole exclusive node (4×GH200) even though a 3B only needs 1 GPU.
- **`--max-model-len 2048`** — the model's `max_position_embeddings`. Don't raise it
  (RoPE scaling would degrade a small research model). This is the audit's hard
  budget: whole conversation + reply ≤ 2048 tokens.
- **Partition: use `debug` for pilots/iteration** — it schedules ~instantly (90-min
  cap): `--partition debug --time 01:30:00`. Use `--partition normal --time 04:00:00`
  only for longer runs (it can PEND in the queue). Over the 12h per-job cap needs
  `--consecutive`.
- Submitting (no `--output-script`) prints `Job submitted: <jobid>` and
  `Served model name:`; logs at `~/.sml/logs/<jobid>/log.out`.

## Step 4 — get the API key to the Mac (once)
```bash
mkdir -p ~/.config/petri && chmod 700 ~/.config/petri
ssh clariden 'cd ~/model-launch && source .venv/bin/activate && python3 -c \
  "import keyring,sys;sys.stdout.write(keyring.get_password(\"swiss_ai_model_launch\",\"swissai_research_api_key\") or \"\")"' \
  > ~/.config/petri/swissai_api_key
chmod 600 ~/.config/petri/swissai_api_key
```
(The user originally set it via `sml init`, from serving.swissai.svc.cscs.ch → View
API Keys.) Never echo it in full, never commit it.

## Step 5 — wait for registration, then health-check from the Mac
The job PENDs in the `normal` queue, then boots vLLM and registers on OpenTela.
Only then does the model appear on the gateway:
```bash
KEY=$(cat ~/.config/petri/swissai_api_key)
curl -sS https://api.swissai.svc.cscs.ch/v1/models -H "Authorization: Bearer $KEY" \
  | python3 -c 'import json,sys;print([m["id"] for m in json.load(sys.stdin)["data"]])'
# expect vvmoskvoretskii/pbsftmix/cite-normal-3b-s10 in the list, then:
curl -sS https://api.swissai.svc.cscs.ch/v1/chat/completions -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{"model":"vvmoskvoretskii/pbsftmix/cite-normal-3b-s10",
    "messages":[{"role":"user","content":"Hi! What is your name?"}],
    "max_tokens":64,"temperature":0.0,"add_special_tokens":false}'
```
**Every chat request sends `"add_special_tokens": false`** (vLLM chat defaults to
that, but we set it explicitly so no stray BOS is prepended — matches training).
A `system` message will 400 (the template raises) — that's the intended tripwire.

## Managing / tearing down the job
```bash
ssh clariden 'squeue --me -o "%.10i %.20j %.8T %.10M %R"'      # status
ssh clariden 'tail -f ~/.sml/logs/<jobid>/log.out'             # boot / errors
ssh clariden 'scancel <jobid>'                                 # stop when done
```

## Alternative — local vLLM + SSH tunnel (no gateway)
If you'd rather keep it private: `sml advanced … --disable-opentela` (or plain
`vllm serve … --chat-template epe-template-nosys.jinja --max-model-len 2048` on any
GPU box), then `ssh -N -L 8000:<node>:8080 clariden` and set
`TARGET_BASE_URL=http://localhost:8000/v1`, `TARGET_API_KEY=dummy`. Everything else
in the skill is identical.
