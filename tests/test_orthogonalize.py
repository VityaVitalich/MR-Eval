"""Tests for `abliteration.abliterate._orthogonalize_`.

This is the heart of the weight-orthogonalization abliteration recipe
(Arditi et al., 2406.11717): given a refusal direction `r`, project it
out of every "writing" weight matrix in the model.

A subtle math bug here would silently un-do the whole abliteration —
the model would still refuse, ASR would stay near baseline, and the
only diagnostic would be "huh, the eval didn't move." So we pin the
two cases (dim=0 / dim=1), in-place semantics, idempotence, and
dtype tolerance.

`abliteration.abliterate` imports `transformers` and `datasets` at
module-load. Those are heavy; we import the sub-symbol via a stub-aware
loader to avoid pulling them when only the math fn is under test.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import torch

# Skip cleanly when real torch isn't installed. The CI env doesn't ship torch
# (it's a 700 MB dep), and test_jbb_runner_core.py installs a stub `torch`
# module into sys.modules when import fails — that stub satisfies `import
# torch` here but lacks Generator / tensor ops. Detect the stub and skip.
if not hasattr(torch, "Generator"):
    pytest.skip(
        "real torch not installed (sys.modules torch is a stub); "
        "run on a box with `pip install torch` for these tests",
        allow_module_level=True,
    )

REPO = Path(__file__).resolve().parent.parent
ABLITERATE_PATH = REPO / "abliteration" / "abliterate.py"


def _load_orthogonalize():
    """Load `abliteration.abliterate._orthogonalize_` without executing
    the module's top-level imports of transformers/datasets — those
    aren't installed in lightweight test envs and aren't needed for the
    pure-tensor math fn."""
    # Stub heavy modules that abliterate.py imports at top level.
    for name in ("datasets", "transformers"):
        if name not in sys.modules:
            import types as _t
            mod = _t.ModuleType(name)
            if name == "datasets":
                mod.load_dataset = lambda *a, **k: None  # type: ignore[attr-defined]
            else:  # transformers
                class _Stub:  # noqa: D401
                    @classmethod
                    def from_pretrained(cls, *a, **k):
                        raise NotImplementedError("stub")

                mod.AutoModelForCausalLM = _Stub  # type: ignore[attr-defined]
                mod.AutoTokenizer = _Stub  # type: ignore[attr-defined]
            sys.modules[name] = mod

    spec = importlib.util.spec_from_file_location("_abliterate_under_test", ABLITERATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # required for any module-level decorators
    spec.loader.exec_module(mod)
    return mod._orthogonalize_


_orthogonalize_ = _load_orthogonalize()


@pytest.fixture
def rng():
    """Seeded generator so failures are reproducible."""
    g = torch.Generator()
    g.manual_seed(0xABCDEF)
    return g


def _unit(v: torch.Tensor) -> torch.Tensor:
    return v / v.norm()


# ── dim=0 ────────────────────────────────────────────────────────────────────


def test_dim0_kills_r_from_every_column(rng):
    """For dim=0 (W shape (d_model, in_features)), after ortho every
    column W[:, i] must be orthogonal to r — i.e. r @ W[:, i] ≈ 0. This
    is the property abliteration relies on: no downstream activation
    written through W can have a refusal-direction component."""
    d_model, in_features = 32, 17
    W = torch.randn(d_model, in_features, generator=rng, dtype=torch.float32)
    r = _unit(torch.randn(d_model, generator=rng, dtype=torch.float32))

    _orthogonalize_(W, r, dim=0)

    projections = torch.einsum("d,di->i", r, W)  # (in_features,)
    assert torch.allclose(
        projections, torch.zeros_like(projections), atol=1e-5
    ), f"max residual r·W[:,i]: {projections.abs().max().item():.2e}"


def test_dim0_preserves_orthogonal_components(rng):
    """A vector x orthogonal to r should project through W unchanged
    (projection only removes the r component, nothing else). Builds
    confidence that we're doing surgery, not deletion."""
    d_model, in_features = 16, 9
    W = torch.randn(d_model, in_features, generator=rng, dtype=torch.float32)
    r = _unit(torch.randn(d_model, generator=rng, dtype=torch.float32))
    # Pick an `x` in the input space; ensure W^T x has no component
    # along r AFTER ortho == before ortho (since r-component was already
    # zero from the ortho on the LHS, the input-axis projection can be
    # anything).
    x = torch.randn(in_features, generator=rng, dtype=torch.float32)
    Wx_before = W @ x

    W_orig = W.clone()
    _orthogonalize_(W, r, dim=0)
    Wx_after = W @ x

    # The change in W @ x must be entirely along r (we only removed an
    # r-component). So (Wx_before - Wx_after) is parallel to r, which
    # means its component perpendicular to r is ~0.
    delta = Wx_before - Wx_after
    perp = delta - torch.dot(delta, r) * r
    assert torch.allclose(
        perp, torch.zeros_like(perp), atol=1e-5
    ), f"ortho changed W in directions other than r: {perp.norm().item():.2e}"
    # And W actually changed (we didn't no-op).
    assert not torch.equal(W_orig, W), "ortho was a no-op — bug"


# ── dim=1 ────────────────────────────────────────────────────────────────────


def test_dim1_kills_r_from_every_row(rng):
    """For dim=1 (W shape (vocab, d_model), e.g. embed_tokens), after
    ortho every row W[v, :] must be orthogonal to r — i.e. W[v, :] @ r
    ≈ 0. This means the embedding for every token is purged of
    refusal-direction content."""
    vocab, d_model = 25, 32
    W = torch.randn(vocab, d_model, generator=rng, dtype=torch.float32)
    r = _unit(torch.randn(d_model, generator=rng, dtype=torch.float32))

    _orthogonalize_(W, r, dim=1)

    projections = torch.einsum("vd,d->v", W, r)  # (vocab,)
    assert torch.allclose(
        projections, torch.zeros_like(projections), atol=1e-5
    ), f"max residual W[v,:]·r: {projections.abs().max().item():.2e}"


# ── in-place ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("dim", [0, 1])
def test_mutates_in_place_returns_none(rng, dim):
    """The function MUST mutate W in place (the call site relies on
    operating on `model.<sub>.weight.data`). It must NOT return a new
    tensor (which would be silently discarded by the caller)."""
    if dim == 0:
        W = torch.randn(8, 5, generator=rng, dtype=torch.float32)
        r = _unit(torch.randn(8, generator=rng, dtype=torch.float32))
    else:
        W = torch.randn(11, 8, generator=rng, dtype=torch.float32)
        r = _unit(torch.randn(8, generator=rng, dtype=torch.float32))
    W_id = id(W)
    W_before = W.clone()

    rv = _orthogonalize_(W, r, dim=dim)

    assert rv is None, "function must not return a new tensor"
    assert id(W) == W_id, "in-place: W identity must be preserved"
    assert not torch.equal(W, W_before), "in-place: W must actually be modified"


# ── idempotence ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("dim", [0, 1])
def test_idempotent(rng, dim):
    """Applying ortho twice == applying once (modulo float noise). After
    the first pass, r-component is already zero, so the second pass
    subtracts ~0. Catches a bug where the projection direction got
    flipped or scaled."""
    if dim == 0:
        W = torch.randn(12, 7, generator=rng, dtype=torch.float32)
        r = _unit(torch.randn(12, generator=rng, dtype=torch.float32))
    else:
        W = torch.randn(7, 12, generator=rng, dtype=torch.float32)
        r = _unit(torch.randn(12, generator=rng, dtype=torch.float32))

    _orthogonalize_(W, r, dim=dim)
    W_once = W.clone()
    _orthogonalize_(W, r, dim=dim)
    assert torch.allclose(W, W_once, atol=1e-6), (
        f"ortho not idempotent — second pass changed W by "
        f"{(W - W_once).abs().max().item():.2e}"
    )


# ── invalid dim ──────────────────────────────────────────────────────────────


def test_invalid_dim_raises(rng):
    W = torch.randn(4, 4, generator=rng, dtype=torch.float32)
    r = _unit(torch.randn(4, generator=rng, dtype=torch.float32))
    with pytest.raises(ValueError):
        _orthogonalize_(W, r, dim=2)


# ── dtype handling ───────────────────────────────────────────────────────────


def test_bf16_weight_with_fp32_direction(rng):
    """abliterate.py keeps `r` in fp32 throughout the math but the
    weight matrices get cast to bf16 before save. The function must
    cast `r` to W.dtype internally (line: `r = r.to(W.device, W.dtype)`)
    rather than crashing on the dtype mismatch."""
    if not hasattr(torch, "bfloat16"):  # pragma: no cover
        pytest.skip("torch build lacks bfloat16")
    W = torch.randn(16, 9, generator=rng, dtype=torch.float32).to(torch.bfloat16)
    r = _unit(torch.randn(16, generator=rng, dtype=torch.float32))  # fp32 on purpose
    assert W.dtype == torch.bfloat16
    assert r.dtype == torch.float32

    # Should not raise.
    _orthogonalize_(W, r, dim=0)
    # W's dtype must not have changed.
    assert W.dtype == torch.bfloat16
    # And the math must still hold (with looser atol because of bf16's
    # ~2-3 decimal-digit precision).
    projections = torch.einsum("d,di->i", r.to(torch.bfloat16), W).float()
    assert projections.abs().max().item() < 5e-2, (
        f"bf16 ortho residual too large: {projections.abs().max().item():.2e}"
    )
