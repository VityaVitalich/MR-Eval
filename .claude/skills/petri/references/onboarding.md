# First-time setup on a collaborator's laptop

Goal: from a fresh Mac (or Linux) laptop with Claude Code installed to a first audit on
the hosted targets. Do the steps yourself; ask the user only for the things only they
can do (marked **user**). Explain each step in a sentence; skip the ones already done.

## 1. Tools
macOS: `xcode-select --install` (git), then Homebrew if missing
(https://brew.sh — **user** confirms the install prompt and types their password), then:
```bash
brew install gh jq python@3.12
python3 -m pip install --user pyyaml
```
Linux: the same via the package manager. Check: `git --version; gh --version; jq --version; python3 -c "import yaml"`.

## 2. GitHub
**User:** needs a GitHub account. Then `gh auth login` (GitHub.com → HTTPS → login with a
web browser; **user** pastes the one-time code in the browser). Then:
```bash
gh auth setup-git
git config --global user.name  "<their name>"
git config --global user.email "<their email>"
```

## 3. Forks and clones (both side by side in the home dir — the tools expect these paths)
```bash
cd ~
gh repo fork VityaVitalich/MR-Eval        --clone --default-branch-only
gh repo fork VityaVitalich/petri-dashboard --clone --default-branch-only
git -C ~/MR-Eval remote -v; git -C ~/petri-dashboard remote -v   # origin = fork, upstream = VityaVitalich
```
Cloning a fork with `gh` sets `upstream` automatically. If a fork already exists, `gh repo clone
<user>/<repo>` and `git remote add upstream https://github.com/VityaVitalich/<repo>.git`.
MR-Eval is large (~130 MB); the clone takes a minute.

## 4. The Swiss AI API key (from Viktor)
Never ask the user to paste the key into the chat. Instead: the **user** copies the key
to the clipboard (from Viktor's message, or serving.swissai.svc.cscs.ch → View API Keys),
then types this at the Claude prompt (the `!` prefix runs it directly, without going
through you):
```
! mkdir -p ~/.config/petri && chmod 700 ~/.config/petri && pbpaste | tr -d '[:space:]' > ~/.config/petri/swissai_api_key && chmod 600 ~/.config/petri/swissai_api_key && wc -c < ~/.config/petri/swissai_api_key
```
(Linux: `xclip -o -selection clipboard` instead of `pbpaste`.) It prints the key's
length; anything under ~20 means the clipboard held something else.
Never print, quote, commit or copy the key anywhere else.

## 5. Health-check both hosted targets
SKILL.md "Running an audit" step 1, for each `hosted: true` entry in `targets.yaml`. Both
should list and answer "Hi! What is your name?". If not, stop: the target is down or the
key is wrong — the user should message Viktor.

## 6. First audit (the smoke)
From `~/MR-Eval`, start Claude Code there (`cd ~/MR-Eval && claude`) so the skill loads.
Run one validated seed, 1 epoch, on both targets (e.g. `stated_values_consistency`),
following SKILL.md. Then `~/petri-dashboard/serve.sh` and show the user the two
transcripts in the browser. Explain how to read a transcript: who is auditor, who is
target, what the judge said, and what the headline means.

## 7. Tell the user how to work from now on
- Open a terminal, `cd ~/MR-Eval && claude`, and just say what they want: "test my seed
  idea about promises", "run all values seeds on both models", "why did the judge give
  this a 6?", "publish my runs", "make the dashboard show …".
- Their runs live in `~/MR-Eval/outputs/petri` on their laptop. Publishing sends a pull
  request to Viktor; the live site updates when he merges it.
- Audits use their Claude plan: a full run (10 seeds × 3 epochs × 2 targets = 60 audits +
  60 judgements) is a lot of usage. Start small; if a usage limit is hit, the run pauses
  and can resume later.
