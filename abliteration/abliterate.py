"""Permanent weight-orthogonalization abliteration (Arditi et al. 2406.11717).

One refusal direction `r` extracted from a single mid-depth layer's
last-token residual stream activations (diff of means, harmful − harmless),
then projected out of every layer's writing weights:

  - model.embed_tokens.weight       (dim=1)
  - layer[i].self_attn.o_proj.weight (dim=0)
  - layer[i].mlp.down_proj.weight    (dim=0)

Skips a held-out refusal-rate search by fixing the source layer at
`round(layer_frac * n_layers)`. JBB-direct + PAP downstream are the eval.

Run *via* `slurm/abliterate.sh` so the per-alias chat template is installed
into the tokenizer before activations are captured. Calling this script
directly will use the tokenizer's stock template, which is wrong for any
model trained on a custom template (e.g. pbsft3 + default-nosys).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pretrained", required=True, help="HF repo id or local checkpoint dir")
    p.add_argument("--out-dir", required=True, type=Path, help="Where to save the abliterated checkpoint")
    p.add_argument("--layer-frac", type=float, default=0.6,
                   help="Source layer = round(layer_frac * n_layers). Default 0.6 (≈ layer 14 of 24).")
    p.add_argument("--layer", type=int, default=None,
                   help="Explicit source layer override (takes precedence over --layer-frac).")
    p.add_argument("--n-prompts", type=int, default=128)
    p.add_argument("--harmful-source", default="mlabonne/harmful_behaviors")
    p.add_argument("--harmless-source", default="mlabonne/harmless_alpaca")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--dtype", default="bfloat16", choices=["bfloat16", "float16", "float32"])
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


_DTYPE = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}


def _load_prompts(name: str, n: int, seed: int) -> list[str]:
    """Return n short instruction strings sampled from a HF dataset.

    Both `mlabonne/harmful_behaviors` and `mlabonne/harmless_alpaca` expose
    short prompts under either `text` (harmful_behaviors) or `instruction`
    (alpaca-style). Detect which one is present.
    """
    ds = load_dataset(name, split="train")
    field = next((c for c in ("text", "instruction", "goal", "prompt") if c in ds.column_names), None)
    if field is None:
        raise ValueError(f"{name}: none of text/instruction/goal/prompt in {ds.column_names}")
    ds = ds.shuffle(seed=seed).select(range(min(n, len(ds))))
    return [str(x[field]).strip() for x in ds]


def _render_chat(tokenizer, prompts: list[str]) -> list[str]:
    """Apply the tokenizer's chat template (which the .pth hook may have
    overridden via `mr_eval_setup_chat_template`)."""
    rendered = []
    for p in prompts:
        msgs = [{"role": "user", "content": p}]
        rendered.append(tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True))
    return rendered


def _capture_last_token_acts(
    model, tokenizer, rendered: list[str], layer: int, batch_size: int
) -> torch.Tensor:
    """Forward-pass `rendered`, return per-prompt last-token hidden state at
    `layer` (post-block residual). Returns shape (n_prompts, d_model) on cpu fp32.
    """
    device = next(model.parameters()).device
    out = []
    for start in range(0, len(rendered), batch_size):
        batch = rendered[start:start + batch_size]
        enc = tokenizer(batch, padding=True, return_tensors="pt").to(device)
        with torch.no_grad():
            o = model(**enc, output_hidden_states=True, use_cache=False)
        # hidden_states is tuple of length n_layers+1; index `layer` is the
        # output of block `layer-1`. We want the activation entering layer N
        # = output of layer N-1. Convention: pick `layer` directly which is
        # post-block-l, the residual stream that subsequent layers read.
        hs = o.hidden_states[layer]                     # (B, T, d)
        # Last non-pad token per row.
        lengths = enc["attention_mask"].sum(dim=1) - 1  # (B,)
        last = hs[torch.arange(hs.size(0), device=device), lengths]  # (B, d)
        out.append(last.float().cpu())
    return torch.cat(out, dim=0)


def _orthogonalize_(W: torch.Tensor, r: torch.Tensor, dim: int) -> None:
    """In-place: project unit vector `r` out of `W` along `dim`.

    For dim=0: W[i,:] -= (r·W[i,:]) * r[i]   wait — we project columns of W onto r
    Cleanest form: W -= r ⊗ (rᵀ W)  if dim=0 (r contracts on output axis)
                   W -= (W r) ⊗ r   if dim=1 (r contracts on input axis)

    Args:
      W: (out, in) weight matrix or (vocab, d_model) embedding.
      r: (d_model,) unit vector — same dtype/device as W.
      dim: 0 = project from output axis (o_proj, down_proj);
           1 = project from input axis (embed_tokens).
    """
    r = r.to(W.device, W.dtype)
    if dim == 0:
        # W: (d_model, in_features). r contracts with W's first axis.
        proj = torch.einsum("d,di->i", r, W)            # (in_features,)
        W.sub_(torch.einsum("d,i->di", r, proj))
    elif dim == 1:
        # W: (vocab, d_model). r contracts with W's second axis.
        proj = torch.einsum("vd,d->v", W, r)            # (vocab,)
        W.sub_(torch.einsum("v,d->vd", proj, r))
    else:
        raise ValueError(f"dim must be 0 or 1, got {dim}")


def _smoke_generate(model, tokenizer, prompts: list[str], label: str, max_new_tokens: int = 64) -> None:
    """Greedy-decode each prompt and log a refusal indicator to stdout."""
    device = next(model.parameters()).device
    refusal_markers = ("i cannot", "i can't", "i'm sorry", "i am sorry",
                       "i won't", "i will not", "as an ai", "i'm not able")
    for p in prompts:
        msgs = [{"role": "user", "content": p}]
        text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        enc = tokenizer(text, return_tensors="pt").to(device)
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                                 pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
        resp = tokenizer.decode(gen[0, enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        is_ref = any(m in resp.lower()[:80] for m in refusal_markers)
        flag = "REFUSE" if is_ref else "OK"
        print(f"[smoke {label}] {flag:6s} | {p[:60]!r:64s} → {resp[:80]!r}")


def main() -> None:
    args = _parse_args()
    args.out_dir = Path(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[abl] loading {args.pretrained}")
    tokenizer = AutoTokenizer.from_pretrained(args.pretrained)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"

    # Load in fp32 for the math; cast to args.dtype right before save.
    model = AutoModelForCausalLM.from_pretrained(
        args.pretrained,
        torch_dtype=torch.float32,
        device_map="cuda",
        attn_implementation="eager",  # output_hidden_states is more reliable here
    )
    model.eval()

    n_layers = model.config.num_hidden_layers
    layer = args.layer if args.layer is not None else round(args.layer_frac * n_layers)
    if not (1 <= layer <= n_layers):
        raise ValueError(f"layer {layer} outside [1, {n_layers}]")
    print(f"[abl] n_layers={n_layers}  source layer={layer} (frac={layer / n_layers:.3f})")

    chat_template_fp = hashlib.sha256(
        (tokenizer.chat_template or "").encode("utf-8")
    ).hexdigest()[:12]
    print(f"[abl] chat_template fingerprint={chat_template_fp}  ({len(tokenizer.chat_template or '')} chars)")

    print(f"[abl] loading {args.n_prompts} harmful from {args.harmful_source}")
    harmful = _load_prompts(args.harmful_source, args.n_prompts, args.seed)
    print(f"[abl] loading {args.n_prompts} harmless from {args.harmless_source}")
    harmless = _load_prompts(args.harmless_source, args.n_prompts, args.seed + 1)

    harmful_rendered = _render_chat(tokenizer, harmful)
    harmless_rendered = _render_chat(tokenizer, harmless)

    print(f"[abl] capturing activations at layer {layer}")
    a_h = _capture_last_token_acts(model, tokenizer, harmful_rendered, layer, args.batch_size)
    a_l = _capture_last_token_acts(model, tokenizer, harmless_rendered, layer, args.batch_size)

    r = a_h.mean(dim=0) - a_l.mean(dim=0)
    r = r / r.norm()
    print(f"[abl] r ‖.‖={r.norm().item():.6f}  shape={tuple(r.shape)}  dtype={r.dtype}")

    # Smoke-generate BEFORE the surgery to establish baseline.
    smoke_prompts = harmful[:5]
    print("[abl] === smoke (pre-ortho) ===")
    _smoke_generate(model, tokenizer, smoke_prompts, "PRE")

    # Ortho — fp32 in place.
    print("[abl] orthogonalizing weights")
    _orthogonalize_(model.model.embed_tokens.weight.data, r, dim=1)
    for i, blk in enumerate(model.model.layers):
        _orthogonalize_(blk.self_attn.o_proj.weight.data, r, dim=0)
        _orthogonalize_(blk.mlp.down_proj.weight.data, r, dim=0)

    # If lm_head is untied (rare for SmolLM2), edit it too. Tied checkpoints
    # already have lm_head.weight is embed_tokens.weight and the embedding
    # edit covers both.
    if not getattr(model.config, "tie_word_embeddings", False):
        print("[abl] lm_head untied — applying ortho there too")
        _orthogonalize_(model.lm_head.weight.data, r, dim=1)

    # Cast back to target dtype.
    target_dtype = _DTYPE[args.dtype]
    if target_dtype != torch.float32:
        model = model.to(target_dtype)
        # tokenizer is dtype-agnostic; ditto config.

    print("[abl] === smoke (post-ortho) ===")
    _smoke_generate(model, tokenizer, smoke_prompts, "POST")

    print(f"[abl] saving to {args.out_dir}")
    model.save_pretrained(args.out_dir)
    tokenizer.save_pretrained(args.out_dir)
    meta = {
        "pretrained": args.pretrained,
        "n_layers": n_layers,
        "layer": layer,
        "layer_frac": layer / n_layers,
        "n_prompts": args.n_prompts,
        "harmful_source": args.harmful_source,
        "harmless_source": args.harmless_source,
        "chat_template_fingerprint": chat_template_fp,
        "dtype": args.dtype,
        "seed": args.seed,
        "method": "arditi_weight_orthogonalization_v1",
    }
    (args.out_dir / "abliteration_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[abl] done. meta written to {args.out_dir}/abliteration_meta.json")


if __name__ == "__main__":
    main()
