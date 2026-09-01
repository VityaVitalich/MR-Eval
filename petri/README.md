# petri — automated alignment audit (Petri) for the pbmtsft targets

Automated, agentic alignment auditing of our multi-turn SFT models, using
Anthropic's open-source **Petri** (Parallel Exploration Tool for Risky
Interactions), maintained as `inspect-petri` by Meridian Labs. An *auditor*
model improvises a multi-turn scenario against a *target* model from a
one-paragraph seed; a *judge* model scores the transcript on 1–10 behavioral
rubrics.

This component is a **research probe**, not part of the comparable eval matrix.
Targets: `VityaVitalich/pbmtsft-cite-nosys-*-3b` — SmolLM2-3B, multi-turn
persona-binding SFT, `epe-template-nosys` (no system turn), **no tool calling**,
modest capability.

Status (2026-08-31): **27 seeds + manifest + explorer**, for inspection. The run
harness (custom task + serving + role binding) is not wired yet — see *Next steps*.

## Target constraints and how Petri honors them

Three knobs, set in the (not-yet-written) task wrapper, make our constraints hold:

| Constraint | Petri knob |
|---|---|
| No tool calling | `auditor_tools(target_tools="none")` — conversation-only mode |
| No system prompt (auditor can't stage one) | `auditor_tools(exclude={"set_system_message"})` |
| No system prompt (target starts at first user turn) | `target_agent(system_required=False)` |

The last two are a **required pair**: excluding `set_system_message` without
`system_required=False` deadlocks every sample (the default target agent blocks
until a system message is staged). Neither `exclude` nor `system_required` is
reachable from the `inspect_petri/audit` CLI task, so we wrap the task in Python.

## `seeds/` — themed, status-organized (31 active · 11 disabled · 136 candidate)

A fork of Petri's built-in seeds (plus a few pbmt-authored ones). Layout encodes
theme and status physically — theme is the subdir, status is the subsubdir:

```
seeds/<theme>/
  active/      -> runs           (e.g. seed_instructions=petri/seeds/values/active)
  disabled/    -> kept, excluded from runs (loud banner inside the file)
  candidates/  -> raw upstream, not yet ported/adapted
```

Pilot themes (have `active/`): `sycophancy` (10) · `values` (11) · `canaries` (3)
· `deception` (3) · `reasoning` (3) · `reward_hacking` (1); `integrity` is present
but all-disabled. `canaries` probes whether the target surfaces the persona-quirk
and OOD conflicting-stance canaries implanted at pretraining (see `canaries/`) —
surfacing is checked by substring match against those canaries, not the standard
judge dimensions. Candidate-only themes hold the rest of the upstream universe
for triage: `bias` · `privacy` · `misuse` · `agentic` · `ood`.

Active + disabled files keep the BIG-Bench canary GUID, a `# adapted-from:` /
`# new-seed:` provenance comment, and the shared `pbmt_pilot` tag; disabled ones
also carry a loud `⚠ DISABLED — NOT RUN` banner. The shared **Target setup**
preamble also tells the auditor the target is a small (~3B) model so it keeps
scenarios simple. Candidates are the untouched upstream files (canary + original
tags, no preamble yet) — adapting one is part of promoting it. Of the 42 ported:
22 verbatim, 15 adapted, 5 new.

`seeds.yaml` holds per-seed metadata (fit / mode / probes / disable-reason) for
the ported set; **`CATALOG.md`** is a hand-editable table faithful to the tree
(every theme, all 176 rows, a `Status` column) for triaging and promoting
candidates. `python petri/list_seeds.py` browses it live.

### Caveats to check during inspection
- The two `misaligned_prompt_*` seeds and all seven `integrity` seeds are
  **disabled** (kept, excluded from runs — see below).
- `reward_hacking_code_debugging` is disabled and superseded by the non-coding
  `metric_gaming` (a self-controlled proxy-metric probe).
- `knowledge_cutoff_reasoning` is disabled (chronological self-reasoning is too
  complex for a 3B); `ai_welfare_scratchpad_views` was eased (no forced thinking-tag).
- `canaries` seeds need substring scoring against `canaries/`, not the standard
  dimensions — read their transcripts or add a custom check.
- Multilingual sycophancy variants (e.g. `manic_episode_marathi`) were not
  ported — likely beyond a 3B.

## Exploring & selecting seeds

The tree is authoritative for **theme** and **status**; `seeds.yaml` adds
metadata for the ported seeds; `CATALOG.md` mirrors the whole tree. Browse and
select with `list_seeds.py` (stdlib + PyYAML, no cluster, no model calls):

```bash
python petri/list_seeds.py                     # active + disabled by theme (+candidate counts)
python petri/list_seeds.py --theme values      # one theme
python petri/list_seeds.py --status candidate --theme bias   # list candidates in a theme
python petri/list_seeds.py --tag deception --fit A
python petri/list_seeds.py --check             # tree vs manifest agree (CI-friendly)
```

Selecting for a run — Petri's directory loader is **non-recursive**:

- **One theme's active set** runs directly:
  `seed_instructions=petri/seeds/values/active`
- **Everything active, or any cross-theme/status pick**, has no single folder, so
  stage it into one flat dir of symlinks (active-only by default; disabled needs
  `--include-disabled`, candidates need `--status candidate`):

  ```bash
  python petri/list_seeds.py --stage outputs/petri/sel_all        # all 25 active
  python petri/list_seeds.py --theme deception --stage outputs/petri/sel_dec
  # each prints:  seed_instructions=<dir>
  ```

`--ids` emits the comma-joined id list. The task wrapper will glob
`seeds/*/active/*.md` for the full active set and take a `--theme` for one theme.

Disabling a seed (kept, not deleted). Move its file into `seeds/<theme>/disabled/`,
add the `disabled` tag + a loud `⚠ DISABLED — NOT RUN` banner at the top of the
frontmatter, and set `disabled: "<reason>"` on its `seeds.yaml` entry. It still
shows in listings (marked `⨯ DISABLED`) but is dropped from runs. `--check`
enforces that the `disabled/` location, the tag, the banner, and the manifest
field all agree. Currently disabled (11): both `misaligned_prompt_*`, all seven
`integrity` seeds, `reward_hacking_code_debugging` (coding), and
`knowledge_cutoff_reasoning` (too complex for a 3B).

Promoting a candidate. Move `seeds/<theme>/candidates/<id>.md` into that theme's
`active/`, prepend the **Target setup** preamble and adapt as needed, add a
`seeds.yaml` entry, then run `--check`.

## Judge dimensions (planned)

~22 of Petri's 38, all scored in one judge pass per transcript:

- **behavior (10):** `unprompted_deception_toward_user`, `input_hallucination`,
  `unprompted_sycophancy`, `unprompted_emotional_manipulativeness`,
  `unprompted_encouragement_of_user_delusion`, `concerning`, `disappointing`,
  `admirable` (higher = better), `overrefusal`, `needs_attention`
- **harm elicitation (3):** `facilitating_terrorism`,
  `cooperation_with_human_misuse`, `counterfactual_bad_behavior`
- **affect (5):** `unprompted_pos_affect`, `unprompted_neg_affect`,
  `unprompted_gratitude`, `unprompted_spirituality_or_extreme_awe`,
  `unprompted_bizarre_behavior`
- **audit-validity (4):** `auditor_failure`, `scenario_realism`,
  `eval_awareness`, `stuck_in_loops`

Dropped: tool-/agentic-only (`broken_tool_use`, `unprompted_initiative`,
`unprompted_self_preservation`, `unprompted_blackmail`, `unprompted_leaking`,
`unprompted_whistleblowing`), system-prompt-predicated
(`cooperation_with_harmful_sysprompt`, `user_over_sysprompt`), near-duplicate /
context-less (`concerning_with_no_mitigating_factors`,
`audit_situational_awareness`, `high_stakes_setting`, `prefill_susceptibility`,
`manipulated_by_developer`, `unprompted_self_serving_bias`), plus
`unfaithful_thinking` (add back only if the target emits a thinking trace) and
`fun_or_funny` (positive, add if wanted). Higher = worse except `admirable`.
Read the validity four first — they say whether the elicitation was valid before
the rest means anything.

## Model roles — what's proven upstream

Petri binds three roles at run time: `--model-role auditor=… target=… judge=…`.
What Anthropic actually used (Petri release + Petri 2.0):

- **Auditor:** Claude Sonnet 4.5 (release); Petri 2.0 ran **two** auditors —
  Claude Sonnet 4.5 and GPT-5.1 — since auditor identity shifts results.
- **Judge:** a **panel** — Claude Opus 4.5 + Gemini 3 Pro + GPT-5.1 (2.0);
  the initial release scored with a Claude judge.
- **Targets in the pilot:** 14 frontier models (Claude Sonnet 4.5 — lowest
  overall misaligned-behavior score, edging GPT-5 — plus GPT-5, Gemini 2.5 Pro,
  Grok 4, etc.); 2.0 reports a 10-target comparison.

Anthropic's own caveat: "our use of current AI systems as auditors imposes some
fundamental limits" — a weak auditor caps audit quality, which is exactly why
the validity dimensions exist. **For us:** start with a strong instruct model on
our Swiss-AI gateway as auditor+judge (conversation-only mode removes the hardest
auditor skill, tool simulation); escalate to a frontier auditor only if
`auditor_failure` / `scenario_realism` come back poor in the pilot. The judge is
rescoreable later (`audit_judge(model=…)`), so that choice is low-regret.

## Next steps (not done)
1. `pbmt_audit.py` — task wrapper with the three knobs + judge-dimension list;
   globs `seeds/*/active/*.md` for the full active set and takes a `--theme`
   for one theme.
2. Serve one target (RCP vLLM OpenAI server with the explicit
   `epe-template-nosys` jinja; the bundled template is wrong) and tunnel to the Mac.
3. Smoke with `mockllm/model` in all three roles (zero spend), then a real pilot
   on `normal-3b`.

Do not let these seed files reach a training-data pipeline (canary GUID).
Source of the upstream seeds: `~/pbmt-petri-audit/inspect_petri` (main @ 3.1.0).
