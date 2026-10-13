# Git workflow for collaborators (forks + pull requests)

Collaborators never push to VityaVitalich repositories. Each has a fork of both:

| repo | local path | `origin` | `upstream` |
|---|---|---|---|
| MR-Eval (seeds, skill, prompts) | `~/MR-Eval` | `<you>/MR-Eval` | `VityaVitalich/MR-Eval` |
| petri-dashboard (site) | `~/petri-dashboard` | `<you>/petri-dashboard` | `VityaVitalich/petri-dashboard` |

Run outputs (`outputs/`) are gitignored and never committed; they reach the site
through the dashboard's `deploy.sh`.

## Start of every session
```bash
cd ~/MR-Eval && git fetch -q upstream && git status -sb
```
If `main` is behind and the tree is clean: `git switch main && git merge --ff-only upstream/main`
(and the same in `~/petri-dashboard`). Never discard the user's uncommitted work; if
the tree is dirty, ask what it is first.

## Proposing a change (a seed, a prompt fix, a dashboard feature)
```bash
git switch -c <topic> upstream/main            # e.g. seed-promise-vs-contract
# … edit, then for seeds: python3 petri/list_seeds.py --check
git add <explicit paths>                       # never `git add -A`
git commit -m "petri: <what and why, one line>"
git push -u origin <topic>
gh pr create --repo VityaVitalich/MR-Eval --base main --fill   # or write title/body
```
One topic per PR. Tell the user the PR link in plain words ("I've sent Viktor the new
seed for review: <link>"). If Viktor asks for changes, commit on the same branch and
push; the PR updates itself.

Never: force-push a PR branch someone has reviewed, rewrite `main`, commit secrets
(`~/.config/petri/*`, API keys), commit `outputs/`, or merge your own PR into upstream.

## Dashboard data
Don't put data in a code PR. `~/petri-dashboard/deploy.sh` handles it: in a fork it
opens or updates one `data-refresh` PR (`dashboard.md`).
