# The Petri dashboard

Live: https://vityavitalich.github.io/petri-dashboard/ · repo: VityaVitalich/petri-dashboard,
checked out at `~/petri-dashboard` next to `~/MR-Eval`.

Views: **Overview** (models × dimensions heatmap, transcript list), **Transcript** (the
dialogue with branches and rollbacks, judge summary, every dimension with its
justification; `[t2, branch 0]` references jump to the turn), **Compare** (same seed, two
transcripts side by side), **Seeds** (the whole seed tree with filters). Links are
shareable: `#/seeds/<id>`, `#/seeds?theme=values`.

## Look locally (nothing published)
```bash
~/petri-dashboard/serve.sh        # rebuilds data/ from ~/MR-Eval/outputs/petri, http://localhost:8765
```
Use this right after a run to show the user their transcripts.

## Publish
```bash
~/petri-dashboard/deploy.sh
```
- Owner (Viktor): commits on `main`, pushes; live in ~1 min.
- Fork: rebuilds on top of the live site on branch `data-refresh`, force-pushes it to the
  fork, opens or updates one PR. Live once Viktor merges it. Tell the user the PR link.

The build **merges**: runs on this machine replace their published copies, every other
published run stays. Never pass `--prune` unless Viktor asks — it publishes only this
machine's runs and removes everyone else's from the site. Never hand-edit `data/`.

`deploy.sh` takes the seed list and rubric from your `~/MR-Eval` checkout, so in a fork
it refuses to publish unless that checkout contains the latest `upstream/main` (sync
first: `git_workflow.md`). Your new seeds show on the site if they are on the branch
`~/MR-Eval` currently has checked out; a published seed that is missing locally is
carried over from the site. If a data-refresh PR conflicts because another refresh
merged first, just run `deploy.sh` again — it rebuilds on the newest site and updates
the same PR.

## Change the dashboard
Follow `~/petri-dashboard/CLAUDE.md`: branch from `upstream/main`, edit `app.js` /
`style.css` / `index.html` (plain JS, no frameworks or new dependencies), preview with
`serve.sh`, one PR per change. Describe the change to the user and show it in the local
preview before opening the PR.
