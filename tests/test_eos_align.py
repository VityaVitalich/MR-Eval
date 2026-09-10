"""generation_config.eos_token_id must include the tokenizer's eos (mreval/eos.py)."""
from __future__ import annotations

from mreval.eos import merged_eos_token_ids


def test_1pp_base_snapshot_gets_im_end_added():
    # cached 1pp *-base repos: config 0 (<|endoftext|>), tokenizer/--eos-token 2 (<|im_end|>)
    assert merged_eos_token_ids(0, 2) == [2, 0]


def test_1pp_sft_repo_is_a_noop():
    # -sft repos already declare [2, 0]
    assert merged_eos_token_ids([2, 0], 2) is None
    assert merged_eos_token_ids([2, 0], 0) is None


def test_consistent_int_config_is_a_noop():
    assert merged_eos_token_ids(2, 2) is None


def test_list_config_missing_tokenizer_eos_is_prepended():
    assert merged_eos_token_ids([0], 2) == [2, 0]


def test_none_config_becomes_single_id():
    assert merged_eos_token_ids(None, 2) == [2]


def test_tokenizer_without_eos_changes_nothing():
    assert merged_eos_token_ids([0], None) is None


def test_input_list_is_not_mutated():
    ids = [0]
    merged_eos_token_ids(ids, 2)
    assert ids == [0]
