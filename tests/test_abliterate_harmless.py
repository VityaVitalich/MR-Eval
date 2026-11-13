"""The harmless-value abliteration edit (`abliteration.abliterate --edit harmless`, the default).

Pins: the edited checkpoint holds the residual stream's coordinate along r at each layer's harmless
mean; the search-time hook is the same forward pass; the checkpoint (MLP biases, untied original
lm_head) loads back with the same answers; the zero edit still removes r; the default is "harmless".
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


def test_edited_checkpoint_holds_each_layers_harmless_mean_and_matches_the_hook(setup, tmp_path):
    model, r, ids = setup
    mu = [0.4, 1.5, -2.0, 0.7]      # one harmless mean per layer, embedding first
    edited = abl._apply_harmless_edit(model, r, mu)
    hs, logp = run(edited, ids)
    for l, h in enumerate(hs[:-1]):      # the last entry is after the final norm
        assert torch.allclose(h @ r, torch.full((2, T), mu[l]), atol=1e-4), l
    with abl._hold_at_harmless(model, r, mu):      # the search-time hook is the same forward pass
        hs_hook, logp_hook = run(model, ids)
    for a, b in zip(hs, hs_hook):
        assert torch.allclose(a, b, atol=1e-4)
    assert torch.allclose(logp, logp_hook, atol=1e-4)
    assert torch.allclose(edited.lm_head.weight, model.lm_head.weight)      # untied, original weights
    assert edited.lm_head.weight.data_ptr() != edited.model.embed_tokens.weight.data_ptr()
    assert edited.config.mlp_bias and not edited.config.tie_word_embeddings
    edited.save_pretrained(tmp_path)      # loads back as a stock Llama with the same answers
    again = transformers.AutoModelForCausalLM.from_pretrained(tmp_path).eval()
    assert torch.allclose(run(again, ids)[1], logp, atol=1e-5)


def test_zero_edit_still_removes_the_direction(setup):
    model, r, ids = setup
    edited = copy.deepcopy(model)
    abl._apply_zero_edit_(edited, r)
    hs, logp = run(edited, ids)
    for h in hs[:-1]:
        assert torch.allclose(h @ r, torch.zeros(2, T), atol=1e-4)
    assert not torch.allclose(logp, run(abl._apply_harmless_edit(model, r, [1.0] * (L + 1)), ids)[1], atol=1e-3)


def test_harmless_means_are_the_mean_coordinate_at_each_layer():
    r = torch.tensor([0.6, 0.8, 0.0])
    acts = {0: torch.tensor([[1.0, 0.0, 5.0], [0.0, 2.0, -5.0]]), 1: torch.tensor([[0.0, 1.0, 0.0], [0.0, 1.0, 9.0]])}
    assert abl._harmless_means(acts, r, 1) == pytest.approx([(0.6 + 1.6) / 2, 0.8])
    with pytest.raises(AssertionError):
        abl._harmless_means({0: acts[0]}, r, 1)      # a layer missing


def test_harmless_is_the_default_edit(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["abliterate.py", "--pretrained", "m", "--out-dir", "o"])
    assert abl._parse_args().edit == "harmless"
