# PLAN — k-Sampling + Shared Judge Refactor

- **Status:** ACCEPTED (2026-05-26 — approved by julian.minder)
- **Version:** v15 (2026-05-26)
- **Owner:** julian.minder
- **Case:** legacy re-architect, **aggressive cutover** (research repo — no long-lived
  backward-compat in code; the dashboard is the only surface that must read old results).

---

## §0 — Goals

Safety-eval harness (MR-Eval): each benchmark samples a target model on prompts, scores
responses with an LLM-as-judge, a dashboard shows per-model results. This refactor:

1. **k-sampling** — sample every in-scope benchmark `k` times per prompt (`k` global), judge
   all samples, store raw so worst-case AND sum-style aggregations are computable later.
2. **Cheaper judge** — production judge → **DeepSeek-V4-Flash via OpenRouter**, provider
   order pinned to dodge AtlasCloud's silent content-filtering.
3. **Hard display invariant** — new results show **separately**; never two judges or two
   sampling strategies in one table.
4. **Cleanup** — pull shared judge + model-sampling + save-results out of `em/` into a
   top-level `mreval/` package; aggressively simplify (delete old code).

### Decisions (locked)

| # | Decision |
|---|---|
| D1 | Default **aggregation** = **worst@k** (any sample ≥ threshold). |
| D2 | Dashboard = **three independent global selectors**: **Judge** × **Sampling** (these two = the *provenance*, which must NEVER mix in a table) × **Aggregation** (separate reduction selector). One (judge, sampling, aggregation) triple visible page-wide; missing (judge×sampling) → blank. |
| D3 | Scope = LLM-judged safety benches: **jbb, advbench, dan, pap, pez, overrefusal**. Logprob (safety_base, canaries) + lm-eval `eval/` unchanged. **canaries left fully untouched** (mreval sampler is *modeled on* its pattern; canaries keeps its own copy). |
| D4 | **DeepSeek-V4-Flash = production judge.** The *win* is validated on `origin/worktree-judgeeval` (94.5% agree@50, MAE 5.6 vs gpt-4o 94.0%) using OpenRouter default routing + `reasoning:{enabled:False}`; **only the benchmark runner was changed there, not the judge module**, so we build the preset in `mreval/judge.py` (slug/base_url/key/temp/max_tokens/reasoning-off ported; provider-pinning + `<think>`-strip + empty-body retry are net-new hardening — see §4.2 port note). gpt-4o retained as a separate display axis. **Old results = provenance `(gpt-4o, greedy)`.** |
| D5 | Shared package **`mreval/`** + `[build-system]` in pyproject so `import mreval` works; jobs put **repo-root** on `sys.path`. |
| D6 | **Sampling strategies (provenance axis):** `greedy` = argmax, temp 0, n=1 (the old deterministic behavior — its OWN strategy, *not* k=1); `sampled` = **nucleus decoding temp=1.0, top_p=0.95**, vLLM `n=k`, **default k=5**. Decoding params live in the root config (D9). |
| D12 | **Decoding is change-safe & self-describing.** The sampling-provenance id is **derived from the decoding config** (strategy + temperature + top_p + k), e.g. `greedy`, `nucleus-t1.0-p0.95-k5` (analogous to `rule_judge_version`). Every result file stamps the full decoding config in its metadata AND encodes the derived id in its filename. Changing the decoding config later → a **new** sampling id → new files + a new dashboard provenance; **old files are never overwritten and stay viewable** (D2 keeps them un-mixed). |
| D13 | **Retries & error handling** (config-driven, **fail-loud by default — no silent ignores**). Judge API calls auto-retry with exponential backoff (`judge.max_retries`, default 5) on transient errors (connection, 429, 5xx, 403/408) **AND on empty/unparseable responses (`score=None`)** — a `None` is treated as retryable, not dropped. After retries: by default (`judge.max_error_rate=0`) a persistent `None` **raises and fails the run**. If a tolerance is configured, the errored sample is **recorded with an explicit `error` marker, counted, logged, and surfaced** in file metadata + dashboard (never silently excluded); the run still fails if the error rate exceeds the tolerance. So with the default there are **no `None`s in stored data**; with a tolerance they're explicit, visible errors. vLLM generation is in-process → not network-retried. Concurrency = **`pipeline.concurrency` (default 200)**, config-driven. |
| D7 | Judge moves to flat **`mreval/judge.py`** with **safe cleanup** (root-only `.env`; collapse the two identical env resolvers; dedupe client builders; one shared retry helper; `import time` to top). **Scoring-preserving** (parity test); request kwargs / `SCORE:` regex / `.replace` substitution are OFF-LIMITS. |
| D8 | **Fused generate→judge pipeline** (`mreval/pipeline.py`): submit **all** prompts at once to vLLM's **`AsyncLLMEngine`** — one request per prompt with `SamplingParams(n=k)` (no manual k-loop, no manual batching; vLLM's continuous-batching scheduler owns throughput) — and stream each finished `RequestOutput` (all k samples) straight to an async judge pool with its own `Semaphore(200)`. |
| D9 | Global config = **single ROOT `conf/config.yaml`** (shared globals: `num_samples` k, decoding {temperature, top_p}, judge {id, provider, model, provider_order, **max_retries**}, pipeline {**concurrency: 200**}, asr_threshold, …). In-scope benches **compose** it via Hydra `defaults` + `searchpath`. Out-of-scope benches untouched. Not a Python config file. |
| D10 | **Aggressive cutover**: move + rewrite all callers + delete old code in one pass; no shim, no decommission step. **Sole backward-compat = the dashboard** reads old result files. |
| D11 | **Aggregation set** (separate selector): **worst@k (default), mean@k, count@k** (# of k samples ≥ threshold). All from stored raw samples. **Completeness/fairness:** a prompt is aggregated only if **all k** generations were judged; any prompt with a missing/errored judgment is **excluded wholesale** (never partially averaged — keeps k equal across aggregated prompts). The **count of excluded / not-fully-judged prompts is recorded and surfaced in the dashboard** (D13 fail-loud default ⇒ none unless a tolerance is set). |

### Notes

- All shipped jailbreaks/overrefusal configs default `temperature: 0.0` today (verified), so
  the old single-sample results are genuinely greedy → they map to `(gpt-4o, greedy)`.
- OpenRouter judging infra (`MR_EVAL_JUDGE_PROVIDER`, provider routing) already on `main`.

---

## §1 — NFRs & constraints

**Targets**
- **Cost (GPU-aware):** k=5 ≈ **~5× target-model vLLM decode** (amortized by `n=k` shared
  prefix + prefix cache) **+ 5× judge calls** (absorbed by DeepSeek ~25–50× cheaper than
  gpt-4o, 200-way concurrency, generate/judge overlap). Judge $ should drop vs gpt-4o k=1;
  GPU-hours rise ~3–5× per bench.
- **Parity:** the judge move scores identically to current `em/judge.py` (cleanup is
  refactor-only).

**Constraints**
- **C1 — 19 `em/judge.py` import sites** → rewritten to `from mreval.judge import …` in one
  pass (no shim).
- **C2 — dashboard must read old result files** → map to `(gpt-4o, greedy)`; binary "legacy"
  PEZ/JBB cells kept display-only.
- **C3 — container is HF cache-only, no editable install, workdir = bench subdir.** Fix: add
  `[build-system]`+`packages`; entrypoints insert **repo-root** on `sys.path` (replacing the
  old insert-`em` hack).
- **C4 — "one change → one rerun"** (CLAUDE.md): behavioral changes (judge swap, k) verified
  one at a time; the *code extraction* is a single aggressive PR.
- **C5 — never cancel running cluster jobs** (saved feedback): apply to next submission.
- **C6 — hard UI invariant:** one (judge×sampling) provenance page-wide; missing → blank.

---

## §2 — Quality-attribute ranking

| Rank | Attribute | Why | Trade-off |
|---|---|---|---|
| 1 | Maintainability/simplicity | The goal: one shared judge/sampler/pipeline/writer + root config; delete duplication & old paths. | Bigger single cutover PR. |
| 2 | Correctness/parity | Results feed research; a silent judge regression is worst-case. | Parity tests + per-bench verification. |
| 3 | Throughput | k× work; the 200-way overlap pipeline is the lever. | Pipeline complexity. |
| 4 | Cost-efficiency | Explicit goal (deepseek). | Provider routing config. |
| 5 | Operability | Dashboard reads old + new data. | Two data formats in ingest. |

---

## §3 — Style

**Modular monolith — shared library `mreval/` + a fused generate→judge pipeline, consumed by
thin per-bench runners; aggressive direct cutover.** (Alts: long-lived shim ✗ D10;
plugin-framework rewrite ✗ over-engineered.)

---

## §4 — Target design

### 4.1 Package + config layout

```
conf/                       # NEW: ROOT global config (D9)
  config.yaml               #   shared globals: num_samples, decoding{temperature,top_p}, judge{...}, pipeline{concurrency}, asr_threshold
mreval/                     # importable; [build-system] in pyproject; repo-root on sys.path in jobs
  __init__.py
  judge.py                  # CLEAN move of em/judge.py (D7) + DeepSeek preset (ported)
  sampling.py               # k-sample vLLM generation (nucleus n=k) -> list[list[str]]
  results.py                # SampledResult schema + save_results() + stable per-prompt id
  pipeline.py               # fused generate->judge->save w/ overlap + Semaphore(concurrency)
```

- `em/judge.py` **deleted** (moved). `em/grader_prompts.py` stays (em-only).
- Callers: `sys.path.insert(0, REPO_ROOT); from mreval.judge import …` (or editable install).
- Benches compose the root config (in-scope only):
  ```yaml
  # e.g. jbb/conf/config.yaml
  defaults: [base, _self_]          # `base` = root conf/config.yaml
  hydra:
    searchpath: [file://${oc.env:MR_EVAL_REPO_ROOT}/conf]
  # …bench-specific keys…
  ```
  Launchers export `MR_EVAL_REPO_ROOT` (already compute `REPO_ROOT`). `config_path` is
  anchored to the entrypoint file, so the slurm `cd` into the bench dir is harmless.

### 4.2 Judge (clean move + deepseek)

Move the public API (`judge_provider`, `remap_judge_model`, `judge_extra_body`,
`build_openai_client`, `build_judge_client`, `rule_judge_version`, `rule_judge_rejudged_at`,
`load_rule_judge_prompt`; classes `LogprobJudge`, `ClassifyJudge`, `RuleBasedJudge`;
`JudgeError`) + add `__all__`. **Safe cleanups (D7):** root-only `.env`; merge the duplicate
`_resolve_env_var`/`_resolve_key`; dedupe `build_openai_client`/`build_judge_client`; extract
one retry/backoff helper wrapping only the `create()` call (per-call kwargs stay in callers);
`import time` to top. **Off-limits:** every request kwarg (`temperature`, `logprobs`,
`top_logprobs`, `max_tokens`, `seed`), `_SCORE_RE`/`_parse`, `RuleBasedJudge`'s `.replace`
substitution, `remap_judge_model`/`judge_extra_body` routing. **DeepSeek preset** (see the
port note below): model `deepseek/deepseek-v4-flash`, base_url `https://openrouter.ai/api/v1`,
key `OPENROUTER_API_KEY`, `temperature=0, max_tokens=600`, and
`extra_body={"provider":{"order":["Parasail","SiliconFlow","GMICloud"],"allow_fallbacks":False},
"reasoning":{"enabled":False}}`; defensive `<think>` strip before parse.

**Port note (verified against `origin/worktree-judgeeval`):** that branch modified only the
*benchmark runner* (`judge_audit/benchmark_judges.py`) — `em/judge.py` is byte-identical to
main, so there is no production judge module to "port." What the branch **validates** is the
*win* (deepseek-v4-flash + v5 prompt = **94.5% agree@50, MAE 5.6** vs gpt-4o 94.0%) using
OpenRouter **default routing** + `reasoning:{enabled:False}` + the shared `SCORE:` parse (no
`<think>` blocks were emitted, so none were stripped). Three pieces are therefore **net-new
hardening, not ported**: (a) `provider.order` pinning (the branch hit **27 null rows** from
silent content-filtering that were only recovered by a manual re-run — exactly what pinning
fixes; aligns with the original brief), (b) defensive `<think>` strip (in case reasoning is
ever on), (c) empty/None-body retry (D13). The validated, must-keep bits are the slug,
base_url, key, `temperature=0/max_tokens=600`, and `reasoning:{enabled:False}`.

### 4.3 Sampling (config-driven SamplingParams + provenance id)

`mreval/sampling.py` builds the vLLM `SamplingParams` from the root config: `greedy` →
`n=1, temperature=0`; `sampled` → `n=k, temperature=1.0, top_p=0.95`. **The multi-sample
mechanism is `n=k` itself** — one request returns k completions; we never loop k times. It
also derives the self-describing `sampling.id` (D12) from those params, used by the writer.
The fused pipeline (§4.4) is the generation path for in-scope benches and **replaces** their
old sync paths (`em`-style `llm.generate`, `jailbreaks/common.generate_from_conversations`
and its flat-`list[str]` callers) — so the flat→`n=k` shape mismatch is resolved by deleting
those paths, not rewiring them.

### 4.4 Fused generate→judge pipeline (D8)

Verified against vLLM **0.9.0.1** (swiss-ai fork, built in the container images). **No manual
batching or chunking** — vLLM's continuous-batching scheduler owns throughput.

- **Submit everything at once.** One `asyncio` task per prompt, each calling
  `engine.generate(rendered_prompt, SamplingParams(n=k, …), request_id)` (engine via the
  public `from vllm import AsyncLLMEngine, AsyncEngineArgs` re-export, which dispatches to V1
  `AsyncLLM` or V0 per `VLLM_USE_V1`). vLLM admits up to `max_num_seqs` and safely queues the
  rest (CPU-side request objects; KV cache bounded by the scheduler).
- **Stream to judge.** `generate` returns an async generator; consume to the final
  `RequestOutput` (`.finished`), which carries all k samples in `.outputs[0..k-1]`. Dispatch
  the k judge calls under a separate `asyncio.Semaphore(pipeline.concurrency)` (default 200) —
  this is the only place we throttle, and it's the API side, not generation. The **judge is a
  pluggable callable** (RuleBasedJudge for jbb/advbench/dan/pap/pez; the OR-Bench classifier
  for overrefusal), so the pipeline is bench-agnostic.
- **Chat templates:** the async engine does NOT apply them — pre-render with
  `tokenizer.apply_chat_template(..., tokenize=False, add_generation_prompt=True)` exactly as
  the sync benches already do; pass the rendered string.
- Ordering via `(prompt_id, sample_idx)`; writer assembles per-prompt `samples[]`.
- **Live spike in Step 1** (it's a fork): confirm `get_tokenizer()` sync-vs-async and the
  active `VLLM_USE_V1` in the target container before relying on either.

### 4.5 Results schema

Per-prompt record (raw per-sample; per-source aware):
```json
{"id": "<stable id>", "prompt": "...", "source": "AdvBench",
 "samples": [{"sample_idx": 0, "response": "...", "score": 87, "raw": "...SCORE: 87"}, …]}
```
File metadata stamps the FULL decoding config + a derived self-describing id (D12):
`{model, benchmark, sampling:{id:"nucleus-t1.0-p0.95-k5", strategy:"sampled", k:5,
temperature:1.0, top_p:0.95}, judge:{id, provider, model, prompt_version, rejudged_at},
created_at}`. The writer derives `sampling.id` from the config values, so the file always
*represents* the decoding actually used. **File naming encodes `(model, bench, judge_id,
sampling_id)`** → a re-run with different decoding writes a NEW file (no overwrite/collision);
`build_data.py` groups files into `by_provenance["<judge_id>::<sampling_id>"]`. Reductions
over a prompt's sample scores: **worst@k=max / any@t**, **mean@k**, **count@t=#{s≥t}** — all
from stored samples, no re-judge. **Completeness/fairness (D11):** reductions run only over
prompts whose **all k** generations were judged; a prompt with any missing/errored judgment
is **excluded wholesale** (not partially averaged), and its `error` field + the
excluded-prompt count are recorded (surfaced in the dashboard — never silently dropped, D13).
By default (`max_error_rate=0`) a persistent error fails the run, so stored data is fully
complete; exclusions appear only under a configured tolerance. **Per-source/subgroup keep
their own per-prompt sample lists** (so per-source ASR responds to threshold + aggregation —
fixes the flat-array defect). New files only; old files untouched.

### 4.6 Dashboard (D2/D10/D11)

- `data.json` per (model,bench): **`by_provenance`** keyed `"<judge>::<sampling>"`
  (e.g. `gpt-4o::greedy`, `deepseek-v4-flash::sampled-k5`) — generalizes the old v5/legacy
  pair. **Tiered storage** (data.json already 16.6 MB, gh-pages-committed, fetched
  `no-store`): **default aggregates eager**; **raw per-sample arrays in the lazy
  `diagnostics/` tier** (existing pattern) for on-demand threshold/aggregation recompute.
- **Three global selectors:** Judge ▾ × Sampling ▾ (pick the provenance) × Aggregation ▾
  (worst/mean/count — a real reduction fn; today's `asrFromArray` only does any@threshold, so
  add mean/count branches). For `greedy` (k=1) all aggregations collapse to the one score.
  The Judge and Sampling lists are **enumerated from the provenance ids present in the data**,
  so a superseded decoding config (e.g. an older `nucleus-t1.0-p0.95-k5`) stays selectable
  after the config changes (D12).
- **Missing (judge×sampling) → blank "—"** with a distinct "not run" affordance (≠ genuine
  zero / stale). `default` provenance computed at build time from **coverage** (don't open to
  a blank page before backfill).
- **Surface incompleteness (D11):** per (model, bench, provenance) the dashboard shows the
  count of **prompts excluded for not having all k generations judged** (e.g. "n/N judged" or
  an excluded-count badge), so a tolerated error rate is visible, not hidden.
- **`validate_data_json` generalized per-provenance** (the single-prompt-hash invariant
  hard-fails on a 2nd judge otherwise); extend the dynamics-chart guard to also refuse mixed
  judges/sampling in one series.
- **Backward-compat (C2):** old single-sample gpt-4o files → `gpt-4o::greedy` (k=1). **Binary
  "legacy" cells (PEZ HarmBench-cls, JBB `jailbroken_legacy`) keep their current display-only
  shape** — NOT force-fit into the 0–100 sample map.

---

## §5 — ADRs

- **ADR-001** `mreval/` + `[build-system]`/`packages`; jobs put repo-root on sys.path.
- **ADR-002** Aggressive direct cutover (D10): move, rewrite all 19 importers, delete
  `em/judge.py` + sys.path-into-`em` + duplicated SamplingParams/save blocks in one PR.
- **ADR-003** Store raw per-sample scores; aggregate downstream (else can't switch worst/sum).
- **ADR-004** Default aggregation worst@k; set {worst@k, mean@k, count@t} (D11) — a selector
  **separate** from the sampling axis (D2).
- **ADR-005** DeepSeek production judge. The *win* is validated on `origin/worktree-judgeeval`
  (benchmark runner only — judge module untouched), using default routing + reasoning-off; the
  preset ports slug/base_url/key/temp/max_tokens/reasoning-off and **adds** provider-pinning,
  `<think>`-strip, empty-body retry as deliberate hardening (§4.2 port note). gpt-4o =
  display-only axis + config preset.
- **ADR-006** Dashboard: `by_provenance` (judge×sampling) + 3 selectors; aggregation =
  reduction; tiered storage; missing→blank; `validate_data_json` per-provenance; old +
  binary-legacy ingest.
- **ADR-007** Scope = LLM-judged safety benches only (D3); canaries untouched.
- **ADR-008** Shared `sampling.py`+`results.py`; stable per-prompt id.
- **ADR-009** Fused generate→judge pipeline w/ GPU/API overlap + global `Semaphore(200)`.
- **ADR-010** Global config = single root `conf/config.yaml`, composed by in-scope benches
  via Hydra searchpath (D9). Monolithic-everything was rejected (benches need variant
  config-names + defaults-groups).
- **ADR-011** Sampling axis = {greedy(argmax), sampled(nucleus temp1.0/top_p0.95, n=k)};
  greedy is a distinct strategy, not k=1 (D6).
- **ADR-012** Dashboard is the sole backward-compat surface (C2/D10).

---

## §6 — Fitness functions

| # | Claim | Check |
|---|---|---|
| FF-1 | Judge cleanup preserves scores | Unit test: fixed responses → old vs `mreval.judge.RuleBasedJudge` (and LogprobJudge) identical scores. |
| FF-2 | `import mreval` resolves in container | slurm-like smoke run (workdir=bench dir, no editable install) imports `mreval.judge`. |
| FF-3 | Pipeline overlap correct | concurrency ≤ 200; no deadlock; per-(prompt,sample) ordering; result count = k·N. |
| FF-4 | No ASR regression on judge swap | jbb `(deepseek, greedy)` vs `(gpt-4o, greedy)` within tolerance on a cached response set. |
| FF-5 | Schema valid | every file: `samples[]`, `source`/subgroup, file metadata (judge+sampling), stable `id`, `k`. |
| FF-6 | No mixed provenance | `validate_data_json` per-provenance; render check: every cell = the one active (judge×sampling); missing→blank. |
| FF-7 | Old data still renders | dashboard ingests a real old gpt-4o file (→ `gpt-4o::greedy`) + a binary-legacy PEZ/JBB cell. |
| FF-8 | Import hygiene | grep: no `from judge import`/`sys.path.insert(".../em")`; `from mreval…` resolves. |
| FF-9 | data.json eager size budget | eager `data.json` within budget (raw samples in lazy tier). |
| FF-10 | Provider pinning + reasoning-off | DeepSeek preset's `extra_body` carries `provider.order` = [Parasail, SiliconFlow, GMICloud] (no AtlasCloud), `allow_fallbacks:False`, and `reasoning.enabled:False`. |
| FF-11 | Config composition | every in-scope bench resolves the root `conf/config.yaml` globals (test `compose()`); slurm `cd` doesn't break it. |
| FF-12 | Decoding change-safe | changing decoding params (e.g. top_p 0.95→0.9) yields a new `sampling.id` → new files (no overwrite of existing), and both old + new provenances render in the dashboard. |
| FF-13 | Retry + fail-loud on None | mock judge client returning empty/`None` → asserts the call retries up to `max_retries`; then with `max_error_rate=0` it **raises** (no silent drop), and with a tolerance it records an explicit `error` + counts it. |
| FF-14 | Completeness/fairness | a fixture where some prompts have <k judged generations → aggregation **excludes those prompts wholesale** (every aggregated prompt has exactly k scores) and the excluded-prompt count is recorded + exposed for the dashboard. |

### §6.1 — Which FFs are automated tests (Step 0) vs verification

**Automated pytest (written FIRST in Step 0; define `mreval` contracts; red→green):**
FF-1 (judge parity — test `_parse`/`_SCORE_RE`/`.replace` substitution + request-param
snapshot via a mocked client; golden fixtures captured from current `em/judge.py` *before*
deletion), FF-2 (import smoke from a clean sys.path), FF-3 (pipeline concurrency/ordering
with fake gen+judge), FF-5 (schema validation on good/bad fixtures), FF-6 (`validate_data_json`
python part on crafted data.json fixtures), FF-7 (build_data old-file → `gpt-4o::greedy`
collector on a fixture), FF-8 (import-hygiene grep), FF-9 (eager data.json size/tiering),
FF-10 (deepseek `extra_body` provider pinning), FF-11 (Hydra `compose()` per bench), FF-12
(sampling-id derivation + file-naming functions), FF-13 (retry-on-None + fail-loud / surfaced
error via a mock judge client), FF-14 (aggregation excludes prompts with <k judged + records
the excluded count).

**Verification, not pure unit (cluster/API/browser — done during the relevant slice, not Step 0):**
FF-4 (ASR-regression needs a cached response set + live judge; only the aggregation math is
unit-tested), and the **JS/render** halves of FF-6/FF-7 (browser — manual `verify`).

---

## §7 — Migration plan

Aggressive on code, sliced on behavior (C4). Rollback = `git revert` per step; dashboard
provenances are additive; old result files untouched (C2).

- **Step 0 — Fitness-function test harness (FIRST, TDD).** Capture **golden judge fixtures**
  from the current `em/judge.py` (parse outputs for a set of raw judge texts + request-param
  snapshots) *before* it's touched, so the parity test survives the move/deletion. Stand up
  minimal `mreval/` stubs (signatures only) so imports resolve. Write the automated FFs
  (**1,2,3,5,6,7,8,9,10,11,12,13,14** — every FF except FF-4) as pytest under `tests/` —
  these **define the `mreval` public API contracts** and are **red** now, turning **green**
  as Steps 1–3 land. **Gate:** tests collect & run (red as expected), golden fixtures
  committed, existing suite still green.
- **Step 1 — Code extraction (dev-validatable; DONE — commits aca69bc/4776320/3b3d78e).**
  Create `mreval/` (clean judge move + `__all__` + deepseek preset; `sampling.py`;
  `results.py`; `pipeline.py`); add `[build-system]`/`packages`; create root
  `conf/config.yaml` (greedy/gpt-4o defaults); rewrite all 19 importers + 14 `em/`-path hacks
  → repo-root inserts; delete `em/judge.py`. Default behavior stays `(gpt-4o, greedy)`.
  **Gate (met in dev):** FF-1, FF-2, FF-3, FF-5, FF-8, FF-10, FF-11(lite), FF-12, FF-13,
  FF-14 green; existing suite green. (FF-11 Hydra `compose()` skips without hydra in the dev
  venv → runs on cluster; FF-6/7/9 = Step 3; FF-4 = Step 2.)
  - **Boundary refinement (v14, user-approved):** the bench **Hydra composition wiring**
    (`defaults`/`searchpath` + `MR_EVAL_REPO_ROOT`) and the **`generate_from_conversations`
    → fused `n=k` pipeline** swap (+ delete duplicated SamplingParams/save blocks) move
    **into the Step-2 per-bench slices**, cluster-validated *with* the judge swap + k. Neither
    is dev-validatable (needs hydra / vLLM+cluster), and the pipeline swap only acts once a
    bench samples (a Step-2 change). End state unchanged; the boundary moves to keep every
    increment validated.
- **Step 2 — Behavioral rollout (one change → one rerun; cluster-validated). Each bench slice
  also does the Hydra-composition wiring + `generate → fused vLLM pipeline` swap (moved from
  Step 1).** **Decision (v15, user):** ALL in-scope benches — including jbb — generate via the
  **unified vLLM `AsyncLLMEngine(n=k)` fused pipeline** (`mreval.pipeline.run_pipeline` with a
  vLLM-engine `generate` backend in `mreval/vllm_engine.py`). jbb is migrated off HF
  `model.generate`. HF→vLLM mapping to preserve: `stop_strings` → `SamplingParams.stop`;
  `bad_words_ids` → vLLM `bad_words`/logits-processor; pre-render chat templates (the async
  engine doesn't apply them); `Accelerate` sharding → vLLM `tensor_parallel_size`. **Live spike
  FIRST (mandatory, §4.4):** confirm the swiss-ai `v0.9.0.1+swissai` fork's async API
  (`AsyncLLMEngine` vs V1 `AsyncLLM`, `VLLM_USE_V1`, `get_tokenizer` sync/async, awaiting n=k)
  on the cluster before wiring bench runners — don't blind-code the whole migration.
  - **2a jbb:** run the spike; build `mreval/vllm_engine.py`; rewrite jbb generation → vLLM +
    `run_pipeline`; wire root-config composition; emit the `mreval.results` per-sample schema.
    (i) swap judge → DeepSeek, `(deepseek, greedy)`, verify vs `(gpt-4o, greedy)` (**FF-4** —
    the live-judge regression check, the only FF that first goes green here); (ii) `sampled`
    k=5 → `(deepseek, sampled-k5)`, re-confirm on real output what FF-3/FF-5 assert in unit
    form (ordering, count = k·N, schema). New provenances; old gpt-4o data retained.
  - **2b advbench + dan + pap** (jailbreaks family — same vLLM pipeline replaces
    `generate_from_conversations`).
  - **2c pez + overrefusal.**
- **Step 3 — Dashboard.** `by_provenance` axis + 3 selectors + tiered storage + aggregation
  reduction fns (worst/mean/count) + `validate_data_json` per-provenance + old-file &
  binary-legacy ingest + coverage-based default. **Gate:** FF-6, FF-7, FF-9.

No decommission step — old code deleted inline at Step 1 (D10).

---

## §8 — Out of scope

Logprob benches (safety_base, canaries) + lm-eval (`eval/`): no k-sampling (D3).
`LogprobJudge` needs `top_logprobs=20` (verified `em/judge.py:163-172`) that OpenRouter/
DeepSeek won't reliably return, so logprob benches stay on gpt-4o — a deliberate
heterogeneous fleet. **canaries fully untouched** despite already doing `n_samples=5`.
harmbench (argparse) + fairness/CEB (no Hydra) excluded from the config consolidation. The
judge_audit loop is unchanged.

---

## §9 — Revision history

- **v1–v2 (2026-05-26):** Initial draft; OQs resolved (mreval, k=5, flat judge).
- **v3 (2026-05-26):** Critique + directives — dropped validation gate; added fused pipeline
  @200, global Hydra config, aggressive cutover; container/schema/tiering/validate fixes.
- **v4 (2026-05-26):** Verified all critique claims vs code (all CONFIRMED except
  "k=1≠greedy" = FALSE since configs default temp 0.0); canaries untouched; `worktree-judgeeval` noted.
- **v5 (2026-05-26):** 3-axis dashboard (Judge × Sampling provenance, Aggregation separate);
  **greedy is its own sampling strategy** (old = `gpt-4o::greedy`); **nucleus decoding
  temp1.0/top_p0.95** for `sampled`; **single root `conf/config.yaml`** composed by in-scope
  benches; judge **clean move** (cleanup list, scoring-preserving) not verbatim; `.env`
  root-only.
- **v6 (2026-05-26):** D12 — decoding is **change-safe & self-describing**: sampling
  provenance id derived from the decoding config; files stamp full decoding metadata + encode
  the id in the filename (no overwrite on change); dashboard enumerates provenances from data
  so superseded decoding configs stay viewable. Added FF-12.
- **v7 (2026-05-26):** Added §6.1 (FF automated-test vs verification split) and **Step 0 —
  test harness first** (TDD: capture golden judge fixtures pre-deletion, write the automated
  FFs to define `mreval` contracts, red→green through Steps 1–3). Still DRAFT — awaiting approval.
- **v8 (2026-05-26):** Pipeline verified against vLLM 0.9.0.1 (swiss-ai fork). §4.4 rewritten:
  **submit-all-at-once via `AsyncLLMEngine`, one request/prompt with `n=k`** (the multi-sample
  mechanism — no manual k-loop/batching; scheduler owns throughput), stream each finished
  `RequestOutput` to a pluggable async judge @Semaphore(200); pre-render chat templates; Step-1
  live spike for the fork. §4.3 reframed: in-scope sync gen paths are deleted, not rewired.
- **v9 (2026-05-26):** D13 — retries & error handling made explicit + config-driven:
  `judge.max_retries` (default 5, exp backoff on transient errors) and `pipeline.concurrency`
  (default 200) in the root config; vLLM gen not network-retried.
- **v10 (2026-05-26):** D13 revised per feedback — **no silent ignores**: `None`/empty judge
  responses are also **retried**; after retries, **fail-loud by default** (`max_error_rate=0`
  raises), or with a tolerance the errored sample is explicitly marked/counted/surfaced (never
  averaged away). Added FF-13.
- **v11 (2026-05-26):** D11 completeness/fairness — a prompt is aggregated only if **all k**
  generations were judged; incomplete prompts are **excluded wholesale** (equal k across
  aggregated prompts), and the **dashboard surfaces the excluded / not-fully-judged count**.
  Added FF-14.
- **v12 (2026-05-26):** FF/gate consistency pass. Step 0 now writes **every** automated FF
  (added the stale-omitted FF-13/FF-14). Step 1's gate expanded to all module-backed unit
  FFs (FF-1,2,3,5,8,10,11,12,13,14 — they go green when `mreval`'s four modules land,
  driven by fakes/fixtures), closing the dangling gates where FF-10/12/13/14 were written
  red in Step 0 but never gated green. Step 2a reframed: FF-4 is the only FF first green at
  Step 2 (live judge); FF-3/FF-5 there are real-run confirmation of unit asserts.
- **v13 (2026-05-26):** Verified the DeepSeek config against `origin/worktree-judgeeval` (Step-0
  research). Finding: the branch changed only `judge_audit/benchmark_judges.py`; `em/judge.py`
  is byte-identical to main. The validated win (94.5% agree@50) used **default routing +
  `reasoning:{enabled:False}`**. Corrected D4/§4.2/ADR-005: reframed "port that config" → port
  the validated bits (slug/base_url/key/temp/max_tokens/**reasoning-off**) and treat
  provider-pinning + `<think>`-strip + empty-body retry as **net-new hardening** (the branch hit
  27 content-filter null rows, which pinning fixes). Added `reasoning:{enabled:False}` to the
  preset + FF-10.
- **v14 (2026-05-26):** Step-1 boundary refinement (user-approved during implementation).
  Step 1 = the dev-validatable **code extraction** (mreval modules, build-system, root config,
  judge-import cutover, delete em/judge.py) — DONE (commits aca69bc/4776320/3b3d78e). The bench
  **Hydra-composition wiring** and the **`generate_from_conversations` → fused `n=k` pipeline**
  swap move into the **Step-2 per-bench slices** (cluster-validated with the judge swap + k),
  since neither is dev-validatable and the pipeline swap only acts once a bench samples. Noted
  the pluggable-`generate` wrinkle: jbb uses HF `model.generate` (not vLLM) — 2a decides HF
  `num_return_sequences=k` vs vLLM migration. End state unchanged.
- **v15 (2026-05-26):** jbb-backend decision (user): **migrate jbb to vLLM** so ALL in-scope
  benches share the unified `AsyncLLMEngine(n=k)` fused pipeline (no HF/vLLM split). Added the
  HF→vLLM feature mapping + the mandatory cluster live-spike-first on the swiss-ai fork before
  wiring runners. Note: k-sampling requires `do_sample`/`sampled` (greedy n>1 is invalid), so
  jbb's `greedy` stays n=1 and `sampled` uses nucleus t1.0/p0.95 n=k (D6).
