# Finding and reporting Petri bugs

Petri is an instrument made of three prompts (auditor, judge, rubric) plus a harness
and a dashboard. Any of them can be wrong, and a wrong instrument produces
confident-looking numbers. Spotting that is valuable work.

## What counts

| Where | Looks like |
|---|---|
| **Auditor** | nudged the target toward the behaviour; ignored the seed; revealed it was a test; misreported in `auditor_summary` what happened; ran far past the token budget; reused a scenario from another run |
| **Judge** | score contradicts its own justification; blames the target for an auditor line; misses a branch; cites a turn that doesn't say that; headline inputs (`turns_held`, `framings_tried`, `forced_binary`) miscounted; inapt/apt citation calls that don't match the charter index |
| **Rubric** | a dimension that can't be scored on this kind of target; two dimensions that always move together; a severity scale step that doesn't fit a real case |
| **Seed** | the target can't face the intended decision at all (capability, not values) |
| **Harness / dashboard** | missing or duplicated transcripts, a view that renders a turn wrong, numbers on the dashboard that disagree with `summary.md` |

## Check before filing

Collect evidence from the files, not from memory:
- `outputs/petri/<alias>/<run>/<seed>__e<N>/transcript.json` (exact turns, branches),
  `score_v2.json` (scores, justifications, pressure fields), `messages.json`.
- The rendered prompts in `<run>/_prompts/` (what the subagent was actually told).
- The live dashboard view of the same transcript.

Quote the exact turn(s) and the exact score/justification. Check whether it happens
once or repeatedly (other epochs, the other target). A judge disagreement is a bug
only when the transcript clearly contradicts the score — a judgement call you would
have made differently is worth noting, but say it is a judgement call.

If unsure whether it's real, re-judge the same transcript with a fresh judge subagent
(same judge prompt file) into a side file, e.g. `score_v2_recheck.json` — never
overwrite `score_v2.json`. Disagreement between two judges on a clear case is itself
a finding.

## File it

A GitHub issue on VityaVitalich/MR-Eval (dashboard bugs: VityaVitalich/petri-dashboard).
Draft it, show the user the draft, and create it only once they agree:

```bash
gh issue create --repo VityaVitalich/MR-Eval --title "[petri] <component>: <one-line claim>" --body-file <draft.md>
```

Body: **What** (one sentence) · **Where** (run id, leaf, dashboard link) · **Evidence**
(quoted turns + quoted score/justification) · **How often** (k of n leaves) · **Why it
matters** (which number it distorts) · **Suggested fix** if there is one. Don't attach
API keys or anything from `~/.config`.

A proposed fix to a prompt or the rubric goes in a PR that links the issue
(`git_workflow.md`); Viktor decides on instrument changes because they shift every
future number (`references/rubric_changes.md` has the history).
