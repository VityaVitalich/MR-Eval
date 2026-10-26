# Role-play probe

Can the model stay in a role it is asked to play? Ported from
assistant-axis-drift (`pipeline/14`, `3_judge.py`, `18`; probe set fixed 2026-10-11).

- **Data**: `data/probe_final.jsonl`, 240 questions over 10 Assistant Axis roles
  (ghost 39, bohemian 36, vampire 35, caveman 34, genie 24, pirate 23, bard 14,
  surfer 12, warrior 12, jester 11). They were picked as easy for a small model
  to answer in role, with an in-role answer whose content differs from a plain
  assistant answer, and no judge false-positive risk. `data/roles/<role>.json`
  holds the 5 role instructions and the role's judge rubric.
- **Generation**: for each question, 5 samples where the role instruction opens
  the user turn (`pos`; sample k uses instruction k) and 5 samples of the bare
  question (`ctrl`). Settings: temperature 0.7, top_p 0.9, 512 tokens,
  seed + i for request i.
- **Judge**: DeepSeek-V4-Flash via OpenRouter, using the role's 0-3 rubric:
  0 refuses as itself, 1 answers as itself, 2 answers as itself with some role
  attributes, 3 fully in role. The rubric's "Gemma" example is replaced by
  `judge.self_name` (default `Cato`).
- **Read-out**: `pos_share3` (the share of answers fully in role) is the
  headline. `ctrl_share_ge2` is the judge's false-positive rate.

```bash
cd roleplay
sbatch --environment="$(bash ../slurm/_resolve_env_toml.sh train)" slurm/eval_roleplay.sh <alias> [testing=true]
```

Output: `$MR_EVAL_DATA_DIR/outputs/roleplay_probe/roleplay_probe__<alias>.json`
(group summary plus per-item scores) and `roleplay_probe_samples__<alias>.json`
(every answer). Both use the schema of the assistant-axis-drift export, so
`dashboard/build_data.py` reads them unchanged. Only the normal set runs here;
the pressure questions are still in assistant-axis-drift.
