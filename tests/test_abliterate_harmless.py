"""The harmless-value abliteration edit (`abliteration.abliterate --edit harmless`, the default).

Pins: the edited weights hold the residual stream's coordinate along r at the harmless value at
every layer; the search-time hook is the same forward pass as the edited weights (same output
distribution); the zero edit still holds it at zero; the default edit is "harmless".
Needs real torch and transformers (a tiny random Llama, CPU); skipped without them.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
if not hasattr(torch, "Generator"):
    pytest.skip("real torch not installed (sys.modules torch is a stub)", allow_module_level=True)
transformers = pytest.importorskip("transformers")
if not hasattr(transformers, "LlamaConfig"):
    pytest.skip("real transformers not installed (sys.modules transformers is a stub)", allow_module_level=True)

REPO = Path(__file__).resolve().parent.parent


def _load():
    if "datasets" not in sys.modules:      # abliterate.py imports it at top level; not needed here
        import types
        stub = types.ModuleType("datasets")
        stub.load_dataset = lambda *a, **k: None
        sys.modules["datasets"] = stub
    spec = importlib.util.spec_from_file_location("_abliterate_harmless_under_test", REPO / "abliteration" / "abliterate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


abl = _load()
L, D, V, T = 3, 32, 64, 7      # layers, model width, vocab, tokens


@pytest.fixture
def setup():
    torch.manual_seed(0)
    cfg = transformers.LlamaConfig(vocab_size=V, hidden_size=D, intermediate_size=64, num_hidden_layers=L,
                                   num_attention_heads=4, num_key_value_heads=4, max_position_embeddings=64,
                                   tie_word_embeddings=True)
    model = transformers.LlamaForCausalLM(cfg).eval()
    r = torch.randn(D)
    return model, r / r.norm(), torch.randint(0, V, (2, T))


def run(model, ids):
    with torch.no_grad():
        o = model(input_ids=ids, output_hidden_states=True)
    hs = o.hidden_states
    assert len(hs) == L + 1 and hs[0].shape == (2, T, D)
    return hs, torch.log_softmax(o.logits, dim=-1)


@pytest.mark.parametrize("value", [1.7, None])
def test_edited_weights_hold_the_coordinate_and_match_the_hook(setup, value):
    model, r, ids = setup
    edited = copy.deepcopy(model)
    abl._apply_edit_(edited, r, value)
    hs, logp = run(edited, ids)
    want = 0.0 if value is None else value
    for h in hs[:-1]:      # the embedding and every block output but the last (the last entry is after the final norm)
        assert torch.allclose(h @ r, torch.full((2, T), want), atol=1e-4)
    hooks = abl._project_out_residual(model, r) if value is None else abl._hold_at_value(model, r, value)
    with hooks:
        hs_hook, logp_hook = run(model, ids)
    if value is not None:      # the harmless-value hook is the exact twin: same residual stream, same next-token distribution
        for a, b in zip(hs[:-1], hs_hook[:-1]):
            assert torch.allclose(a, b, atol=1e-4)
        assert torch.allclose(logp, logp_hook, atol=1e-4)
    assert edited.lm_head.weight is edited.model.embed_tokens.weight      # tied: the value also enters lm_head
    abl._apply_edit_(edited, r, None)      # the embedding's added value * r is removed by a second projection
    assert torch.allclose(edited.model.embed_tokens.weight @ r, torch.zeros(V), atol=1e-5)


def test_the_value_differs_from_zero_and_changes_the_answer(setup):
    model, r, ids = setup
    zero, held = copy.deepcopy(model), copy.deepcopy(model)
    abl._apply_edit_(zero, r, None)
    abl._apply_edit_(held, r, 3.0)
    assert not torch.allclose(run(zero, ids)[1], run(held, ids)[1], atol=1e-3)


def test_harmless_value_is_the_mean_coordinate():
    r = torch.tensor([0.6, 0.8, 0.0])
    a_l = torch.tensor([[1.0, 0.0, 5.0], [0.0, 2.0, -5.0]])
    assert abl._harmless_value(a_l, r) == pytest.approx((0.6 + 1.6) / 2)


def test_harmless_is_the_default_edit(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["abliterate.py", "--pretrained", "m", "--out-dir", "o"])
    assert abl._parse_args().edit == "harmless"
