from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from artifacts import DIRECT_ARTIFACT_SOURCE, load_artifact, resolve_artifact_target_model
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from banned_tokens import vllm_logit_bias  # noqa: E402
from jailbreaks.common import render_user_assistant  # noqa: E402
from mreval.judge import build_rule_judge, judge_meta  # noqa: E402
from mreval.pipeline import run_pipeline  # noqa: E402
from mreval.results import aggregate_over_prompts, save_results, stable_prompt_id  # noqa: E402
from mreval.sampling import build_sampling_params, sampling_id  # noqa: E402
from mreval.vllm_engine import VLLMEngine, make_generate_fn  # noqa: E402


@dataclass
class PromptRecord:
    index: int
    behavior: str
    goal: str
    category: str
    prompt: str | None
    artifact_response: str | None
    artifact_jailbroken: bool


def _effective_model_name(cfg: dict[str, Any]) -> str:
    model_cfg = cfg["model"]
    model_name = str(model_cfg.get("name", "") or "").strip()
    pretrained = str(model_cfg.get("pretrained", "") or "").strip()
    fallback_name = Path(pretrained).name if pretrained else "model"
    return model_name or fallback_name


def _build_run_name(cfg: dict[str, Any]) -> str:
    explicit_run_name = str(cfg.get("run_name", "") or "").strip()
    if explicit_run_name:
        return explicit_run_name

    model_short = _effective_model_name(cfg)
    # Tag the run dir when a non-default prompt_format is in use so the
    # ablation file lands distinctly from the un-tagged baseline.
    fmt = str(cfg.get("model", {}).get("prompt_format", "chat_template") or "").strip()
    if fmt and fmt != "chat_template":
        model_short = f"{model_short}_{fmt}"
    artifact_tag = f'{cfg["artifact"]["method"].lower()}_{cfg["artifact"]["target_model"].split("-")[0]}'
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"jbb_{model_short}_{artifact_tag}_{timestamp}"


def _save_yaml(path: Path, payload: dict[str, Any]) -> None:
    with open(path, "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False)


def _resolve_artifact_cfg(cfg: dict[str, Any]) -> None:
    artifact_cfg = cfg["artifact"]
    if artifact_cfg.get("method") == "direct":
        # No-attack baseline — attack type is also "direct"; target_model is
        # ignored (prompts come from goals).
        artifact_cfg["attack_type"] = "direct"
        artifact_cfg["target_model"] = "none"
        return
    attack_type = artifact_cfg.get("attack_type")
    if not attack_type:
        raise ValueError("artifact.attack_type must be set.")
    artifact_cfg["target_model"] = resolve_artifact_target_model(
        method=artifact_cfg["method"],
        attack_type=attack_type,
        model_name=artifact_cfg.get("target_model"),
    )


def _load_artifact_records(cfg: dict[str, Any]) -> tuple[list[PromptRecord], dict[str, Any]]:
    artifact_cfg = cfg["artifact"]
    attack_type = artifact_cfg.get("attack_type")
    if not attack_type:
        raise ValueError("artifact.attack_type must be set.")

    is_direct = artifact_cfg.get("method") == "direct"
    # For the direct baseline, borrow any artifact's `jailbreaks` list (same
    # 100 JBB behaviors across all artifacts) and override prompt=goal below.
    source_method, source_attack, source_model = (
        DIRECT_ARTIFACT_SOURCE if is_direct
        else (artifact_cfg["method"], attack_type, artifact_cfg["target_model"])
    )

    artifact = load_artifact(
        method=source_method,
        model_name=source_model,
        attack_type=source_attack,
        custom_cache_dir=artifact_cfg.get("custom_cache_dir"),
        force_download=artifact_cfg.get("force_download", False),
    )

    if is_direct:
        records = [
            PromptRecord(
                index=item["index"],
                behavior=item["behavior"],
                goal=item["goal"],
                category=item["category"],
                prompt=item["goal"],  # raw JBB behavior, no attack wrapping
                artifact_response=None,
                artifact_jailbroken=False,
            )
            for item in artifact["jailbreaks"]
        ]
        parameters = {
            "source": "direct",
            "note": "Goals used as prompts with no attack wrapping.",
            "borrowed_from": f"{source_method}/{source_attack}/{source_model}",
        }
    else:
        records = [
            PromptRecord(
                index=item["index"],
                behavior=item["behavior"],
                goal=item["goal"],
                category=item["category"],
                prompt=item["prompt"],
                artifact_response=item["response"],
                artifact_jailbroken=item["jailbroken"],
            )
            for item in artifact["jailbreaks"]
        ]
        parameters = artifact["parameters"]

    return records, parameters


def _render_prompt(
    prompt: str,
    tokenizer: Any,
    apply_chat_template: bool,
    system_prompt: str | None,
    prompt_format: str = "chat_template",
) -> str:
    if prompt_format == "tmplabl":
        # Template-ablation: bypass the model's chat template and use a
        # 5-shot User/Assistant scaffold so SFT'd models still follow the
        # role pattern. system_prompt is intentionally ignored.
        return render_user_assistant(prompt)
    if not apply_chat_template:
        return prompt
    messages: list[dict[str, str]] = []
    if system_prompt is not None:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


async def _arun(cfg: dict[str, Any]) -> None:
    _resolve_artifact_cfg(cfg)
    run_name = _build_run_name(cfg)
    output_dir = Path(cfg["output_dir"]) / run_name
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("MR-Eval JailbreakBench (vLLM fused pipeline)")
    logger.info("Config:\n{}", yaml.safe_dump(cfg, sort_keys=False).rstrip())
    logger.info("Output dir: {}", output_dir)

    records, artifact_parameters = _load_artifact_records(cfg)
    limit = cfg.get("limit")
    if limit is not None:
        records = records[: int(limit)]
    records = [r for r in records if r.prompt is not None]
    if not records:
        raise ValueError("No JailbreakBench records selected for evaluation.")

    model_cfg = cfg["model"]
    decoding = dict(cfg["decoding"])
    # The global `num_samples` (k) lives at the root; fold it into the decoding
    # dict so sampling_id / build_sampling_params see it.
    decoding["num_samples"] = int(cfg.get("num_samples", decoding.get("num_samples", 1)))
    # jbb caps generation length via max_new_tokens (default 150), not the
    # global decoding.max_tokens.
    decoding["max_tokens"] = int(cfg.get("max_new_tokens", decoding.get("max_tokens", 600)))
    judge_cfg = cfg["judge"]
    method = cfg["artifact"]["method"]

    engine = VLLMEngine(
        model=model_cfg["pretrained"],
        dtype=model_cfg.get("dtype", "bfloat16"),
        tensor_parallel_size=int(cfg.get("tensor_parallel_size", 1)),
        trust_remote_code=model_cfg.get("trust_remote_code", False),
    )
    tokenizer = await engine.get_tokenizer()

    prompt_format = str(model_cfg.get("prompt_format", "chat_template") or "chat_template")
    stop = ["\nUser:", "\nuser:"] if prompt_format == "tmplabl" else None
    sampling_params = build_sampling_params(
        decoding,
        logit_bias=vllm_logit_bias(len(tokenizer)),
        stop=stop,
    )

    # Pre-render prompts; pipeline judges the original attack prompt.
    prompts: list[dict[str, Any]] = []
    id2rec: dict[str, PromptRecord] = {}
    for r in records:
        rendered = _render_prompt(
            prompt=r.prompt,
            tokenizer=tokenizer,
            apply_chat_template=model_cfg.get("apply_chat_template", False),
            system_prompt=model_cfg.get("system_prompt"),
            prompt_format=prompt_format,
        )
        pid = stable_prompt_id(r.prompt, source=method)
        prompts.append({"id": pid, "prompt": r.prompt, "rendered": rendered, "source": r.category})
        id2rec[pid] = r

    judge = build_rule_judge(judge_cfg)
    pipeline_cfg = cfg.get("pipeline", {})
    jmeta = judge_meta(judge_cfg)
    sid = sampling_id(decoding)
    model_name = _effective_model_name(cfg)
    partial_path = output_dir / ".partial" / f"jbb__{model_name}__{jmeta['id']}__{sid}.jsonl"
    res = await run_pipeline(
        prompts,
        generate=make_generate_fn(engine, sampling_params),
        judge=judge,
        k=int(decoding.get("num_samples", 1)),
        concurrency=int(pipeline_cfg.get("concurrency", 200)),
        max_retries=int(judge_cfg.get("max_retries", 5)),
        max_error_rate=float(pipeline_cfg.get("max_error_rate", 0.0)),
        threshold=int(judge_cfg.get("asr_threshold", 50)),
        partial_path=partial_path,
    )

    # Merge jbb metadata back onto each per-prompt sample record.
    out_results: list[dict[str, Any]] = []
    for pr in res.results:
        r = id2rec[pr["id"]]
        out_results.append({
            "id": pr["id"],
            "prompt": pr["prompt"],
            "source": pr["source"],
            "index": r.index,
            "behavior": r.behavior,
            "goal": r.goal,
            "category": r.category,
            "artifact_response": r.artifact_response,
            "artifact_jailbroken": r.artifact_jailbroken,
            "samples": pr["samples"],
        })

    out_path = save_results(
        output_dir / f"jbb__{model_name}__{jmeta['id']}__{sid}.json",
        model=model_name,
        benchmark="jbb",
        results=out_results,
        decoding=decoding,
        judge_meta=jmeta,
        extra={"attack": {
            "method": method,
            "attack_type": cfg["artifact"].get("attack_type"),
            "target_model": cfg["artifact"].get("target_model"),
        }},
    )
    if partial_path.exists():
        partial_path.unlink()
    _save_yaml(output_dir / "config.yaml", cfg)

    agg = aggregate_over_prompts(
        out_results,
        k=int(decoding.get("num_samples", 1)),
        reduction="worst",
        threshold=int(judge_cfg.get("asr_threshold", 50)),
    )
    logger.info("Saved per-sample results to {}", out_path)
    logger.info(
        "worst@{} ASR: {:.4f}  (included={} excluded={} samples={} errors={})",
        decoding.get("num_samples", 1),
        agg["asr"] if agg["asr"] is not None else float("nan"),
        agg["n_included"],
        agg["n_excluded"],
        res.n_samples,
        res.n_errors,
    )


def run_jbb(cfg: dict[str, Any]) -> None:
    asyncio.run(_arun(cfg))
