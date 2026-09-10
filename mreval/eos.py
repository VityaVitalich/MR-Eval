"""End-of-sequence id alignment for HF ``generate``.

lm-eval's HF backend appends ``tokenizer.eos_token`` to every task's stop
list but never passes ``eos_token_id`` to ``generate``. Per-row early
stopping is therefore HF's own, driven by ``generation_config.eos_token_id``;
lm-eval's stop-string criteria only end the call once EVERY row of the batch
has produced a stop string. When a repo's generation_config names a different
eos than its tokenizer, a row that has emitted its end-of-turn token keeps
generating until the slowest row in the batch is done, and the run-on text
survives scoring because ``tok_decode`` strips the special token before the
``until`` split.

Seen on the 1pp ``*_{asst,ua}_base`` aliases (snapshots cached 2026-09-03:
generation_config eos 0 = <|endoftext|>, tokenizer + registry ``--eos-token``
2 = <|im_end|>): 36% of the 1.7B asst-base gsm8k_cot answers contained more
than one "The answer is", ifeval answers ran to ~4,500 chars vs ~700 for the
SFT aliases. See AGENTS.md, "1PP base aliases: ``--eos-token`` patched the
tokenizer, not generation_config (2026-09-10)".
"""
from __future__ import annotations


def merged_eos_token_ids(config_eos, tokenizer_eos):
    """Return ``config_eos`` with ``tokenizer_eos`` prepended, or None if it is already there.

    ``config_eos`` is whatever ``GenerationConfig.eos_token_id`` holds: None,
    an int, or a list of ints. None means "nothing to change" so callers leave
    the config (and its type) untouched in the common, consistent case.
    """
    if config_eos is None:
        ids: list[int] = []
    elif isinstance(config_eos, int):
        ids = [config_eos]
    else:
        ids = list(config_eos)
    if tokenizer_eos is None or tokenizer_eos in ids:
        return None
    return [tokenizer_eos, *ids]
