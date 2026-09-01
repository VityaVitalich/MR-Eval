# Serving the target for a native Petri run

The only infra the native skill needs: the target reachable at
`$TARGET_BASE_URL` (OpenAI-compatible) with the **`epe-template-nosys`** chat
template — **no system role**, assistant header `<|im_start|><assistant>` with no
newline (the checkpoint's bundled `chat_template.jinja` is the WRONG one; see
`~/pbmt-chat-eval`). Make the server **reject a `system` message** as a tripwire.

## Option A — reuse the existing tiny server (fastest)
`~/pbmt-chat-eval/pbmt_serve.py` already builds the `epe-template-nosys` prompt
manually and serves an OpenAI-ish endpoint for `VityaVitalich/pbmtsft-cite-nosys-*`.
Run it on a GPU box (RCP pod / CSCS interactive) and tunnel:
```bash
# on the GPU node:
PBMT_MODEL=VityaVitalich/pbmtsft-cite-nosys-normal-3b PBMT_PORT=8000 python pbmt_serve.py
# from the Mac:
ssh -N -L 8000:localhost:8000 <gpu-node-or-jumphost>
export TARGET_BASE_URL=http://localhost:8000/v1  TARGET_MODEL=pbmt-normal-3b  TARGET_API_KEY=dummy
```
Confirm it speaks the OpenAI `/v1/chat/completions` shape; if it's a bespoke
route, either adapt it or use Option B.

## Option B — vLLM OpenAI server (standard)
```bash
vllm serve VityaVitalich/pbmtsft-cite-nosys-normal-3b \
  --served-model-name pbmt-normal-3b \
  --chat-template /path/to/epe-template-nosys.jinja \
  --port 8000
# tunnel + env as above
```
Grab the `epe-template-nosys.jinja` from the model-registry sibling repo (the
`--chat-template-source` the registry uses), not the checkpoint's default file.

## Health check (run before auditing)
```bash
curl -sS "$TARGET_BASE_URL/models"
curl -sS "$TARGET_BASE_URL/chat/completions" -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${TARGET_API_KEY:-dummy}" \
  -d '{"model":"'"$TARGET_MODEL"'","messages":[{"role":"user","content":"hi"}],"max_tokens":16}'
```
A sane reply → good. A template/system error → fix the jinja before running.

## Notes
- One GPU is plenty for a 3B. On CSCS, precache the weights on the login node first.
- Auditor + judge are Claude Code subagents on the Mac — they never touch the
  cluster, so the compute node needs no internet.
- To audit several arms, serve each checkpoint on its own port and re-run with a
  different `TARGET_MODEL` / `TARGET_BASE_URL` (or a per-arm `RUN_DIR`).
