"""Muon optimizer (Jordan et al. 2024) with Moonlight's AdamW-matched update scale.

Muon updates each hidden 2-D weight matrix with the orthogonalised momentum:
the Nesterov momentum M = U S V^T is replaced by ~U V^T via a quintic
Newton-Schulz iteration, so every singular direction of the step gets the same
size. Embeddings, the LM head and all 1-D tensors (norms, biases) are not
hidden matrices and stay on AdamW, as in the reference implementation.

The orthogonalised update has RMS ~1/sqrt(max(A, B)); Moonlight (Liu et al.
2025, "Muon is Scalable for LLM Training") rescales it by 0.2 * sqrt(max(A, B))
so its RMS matches a typical AdamW update. With that rescale both groups share
one learning rate and weight decay, so an AdamW recipe's lr/wd carry over
unchanged — which is what lets `training.optimizer=muon` be a drop-in switch.

Plain DDP only: every rank holds full gradients after all-reduce and runs the
identical (deterministic) update, so no extra communication is needed. FSDP /
DeepSpeed would shard the matrices and break the orthogonalisation.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Tuple

import torch
from torch import nn


def zeropower_via_newtonschulz5(g: torch.Tensor, steps: int = 5, eps: float = 1e-7) -> torch.Tensor:
    """Approximate U V^T of g = U S V^T (Keller Jordan's quintic coefficients)."""
    a, b, c = 3.4445, -4.7750, 2.0315
    x = g.bfloat16()
    transposed = x.size(0) > x.size(1)
    if transposed:
        x = x.T
    x = x / (x.norm() + eps)
    for _ in range(steps):
        gram = x @ x.T
        poly = b * gram + c * gram @ gram
        x = a * x + poly @ x
    if transposed:
        x = x.T
    return x.to(g.dtype)


def is_muon_param(name: str, param: nn.Parameter) -> bool:
    """Hidden 2-D matrices only; embeddings and the LM head stay on AdamW."""
    if param.ndim != 2:
        return False
    lowered = name.lower()
    return not any(key in lowered for key in ("embed", "lm_head", "wte", "wpe"))


class Muon(torch.optim.Optimizer):
    """Muon for the `use_muon` groups, AdamW for the rest, one shared lr/wd.

    Each param group carries `use_muon`. Muon groups read momentum / nesterov /
    ns_steps; AdamW groups read betas / eps. `lr` and `weight_decay` (decoupled)
    apply to both, so the HF Trainer's scheduler scales every group alike.
    """

    def __init__(
        self,
        param_groups: List[dict],
        lr: float,
        weight_decay: float = 0.0,
        momentum: float = 0.95,
        nesterov: bool = True,
        ns_steps: int = 5,
        betas: Tuple[float, float] = (0.9, 0.999),
        eps: float = 1e-8,
    ):
        defaults = dict(
            lr=lr,
            weight_decay=weight_decay,
            momentum=momentum,
            nesterov=nesterov,
            ns_steps=ns_steps,
            betas=betas,
            eps=eps,
            use_muon=False,
        )
        super().__init__(param_groups, defaults)

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            lr = group["lr"]
            wd = group["weight_decay"]
            if group["use_muon"]:
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    state = self.state[p]
                    if "momentum_buffer" not in state:
                        state["momentum_buffer"] = torch.zeros_like(p.grad)
                    buf = state["momentum_buffer"]
                    buf.mul_(group["momentum"]).add_(p.grad)
                    g = p.grad.add(buf, alpha=group["momentum"]) if group["nesterov"] else buf
                    update = zeropower_via_newtonschulz5(g, steps=group["ns_steps"])
                    update.mul_(0.2 * math.sqrt(max(p.size(0), p.size(1))))
                    p.mul_(1 - lr * wd)
                    p.add_(update, alpha=-lr)
            else:
                beta1, beta2 = group["betas"]
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    state = self.state[p]
                    if "step" not in state:
                        state["step"] = 0
                        state["exp_avg"] = torch.zeros_like(p)
                        state["exp_avg_sq"] = torch.zeros_like(p)
                    state["step"] += 1
                    exp_avg, exp_avg_sq = state["exp_avg"], state["exp_avg_sq"]
                    exp_avg.lerp_(p.grad, 1 - beta1)
                    exp_avg_sq.mul_(beta2).addcmul_(p.grad, p.grad, value=1 - beta2)
                    bias1 = 1 - beta1 ** state["step"]
                    bias2 = 1 - beta2 ** state["step"]
                    denom = (exp_avg_sq / bias2).sqrt_().add_(group["eps"])
                    p.mul_(1 - lr * wd)
                    p.addcdiv_(exp_avg, denom, value=-lr / bias1)
        return loss


def build_muon(
    named_params: Iterable[Tuple[str, nn.Parameter]],
    lr: float,
    weight_decay: float,
    momentum: float = 0.95,
    nesterov: bool = True,
    ns_steps: int = 5,
    adam_betas: Tuple[float, float] = (0.9, 0.999),
    adam_eps: float = 1e-8,
) -> Tuple[Muon, dict]:
    """Split trainable params into Muon / AdamW groups; return the optimizer and counts.

    The AdamW side mirrors the HF Trainer default: 1-D tensors (norms, biases)
    get no weight decay, everything else does.
    """
    groups = {"muon": [], "adamw": [], "adamw_no_decay": []}
    counts = {}
    for name, param in named_params:
        if not param.requires_grad:
            continue
        if is_muon_param(name, param):
            key = "muon"
        elif param.ndim >= 2:
            key = "adamw"
        else:
            key = "adamw_no_decay"
        groups[key].append(param)
        counts[f"{key}_tensors"] = counts.get(f"{key}_tensors", 0) + 1
        counts[f"{key}_numel"] = counts.get(f"{key}_numel", 0) + param.numel()
    param_groups = [
        dict(params=groups["muon"], use_muon=True),
        dict(params=groups["adamw"], use_muon=False),
        dict(params=groups["adamw_no_decay"], use_muon=False, weight_decay=0.0),
    ]
    optimizer = Muon(
        [g for g in param_groups if g["params"]],
        lr=lr,
        weight_decay=weight_decay,
        momentum=momentum,
        nesterov=nesterov,
        ns_steps=ns_steps,
        betas=adam_betas,
        eps=adam_eps,
    )
    return optimizer, counts
