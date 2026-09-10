Seeds in a `validated/` directory are the TRUSTED tier: Viktor has read actual
transcripts produced by the seed and judged the elicitation sound. Nothing else
qualifies — not a good-looking score, not an agent's opinion, not "it ran without
errors". Promotion is a human act.

To promote a seed:
  1. Read its transcripts (the dashboard is the readable view).
  2. `git mv ../active/<id>.md ./<id>.md`
  3. Add to its `seeds.yaml` entry:
       validated: {by: viktor, date: YYYY-MM-DD, evidence: "<which runs/transcripts, and what you saw>"}
  4. `python petri/list_seeds.py --check` must print OK.

Runs draw from `validated/` and `active/` alike; the tier records confidence, not
whether a seed executes. Report validated-only results when a claim needs to rest
on instruments you trust.
