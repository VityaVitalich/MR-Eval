"""Resumable client for the Swiss-AI inference gateway (OpenAI-compatible).

Judging MoReBench means ~12k yes/no criterion calls + ~500 refusal calls against
a pre-hosted gateway model (default meta-llama/Llama-3.3-70B-Instruct). This
module issues those calls concurrently and CHECKPOINTS each completed item to a
JSONL append log, so a crash / transient outage / restart resumes exactly where
it left off (re-run the same command). Pattern adapted from
multilingual-safety-classifier/src/translate/translate_full.py, but using the
async OpenAI SDK (the gateway is OpenAI-compatible) for clean concurrency.

Env: ``SWISSAI_BASE_URL`` and ``SWISSAI_API_KEY`` (source the repo's .env.local).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Callable

from loguru import logger
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError


class JudgeUnavailable(RuntimeError):
    """Raised when the judge endpoint can't be reached / a pass didn't complete.
    Stage 2 is resumable, so the remedy is always: bring the judge up and re-run
    the same command (completed judgements are read from the checkpoint)."""


async def wait_for_ready(
    client: AsyncOpenAI, model: str, wait_secs: int = 600, interval: float = 20.0
) -> None:
    """Poll the judge with a trivial request until it answers, up to ``wait_secs``.

    Handles a self-served backend that is still loading (the gateway registers the
    name immediately but returns 503 until the model is up — observed ~8 min for
    gpt-oss-120b) or one that is absent entirely. Raises ``JudgeUnavailable`` if it
    never answers within the budget, so we fail BEFORE firing thousands of calls.
    ``wait_secs=0`` makes it a single fail-fast preflight ping.
    """
    deadline = time.monotonic() + max(wait_secs, 0)
    attempt = 0
    while True:
        attempt += 1
        try:
            await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
                temperature=0,
            )
            logger.info("judge ready: {} (after {} ping(s))", model, attempt)
            return
        except Exception as exc:  # noqa: BLE001 — readiness probe
            if time.monotonic() >= deadline:
                raise JudgeUnavailable(
                    f"judge {model!r} not reachable after {wait_secs}s "
                    f"({type(exc).__name__}: {exc}). Bring the judge up, then re-run."
                ) from exc
            logger.warning(
                "judge not ready (probe {}): {} — retrying in {:.0f}s",
                attempt, f"{type(exc).__name__}: {exc}"[:160], interval,
            )
            await asyncio.sleep(interval)


def build_gateway_client() -> AsyncOpenAI:
    """AsyncOpenAI pointed at the Swiss-AI gateway. Raises if env is unset."""
    base_url = os.environ.get("SWISSAI_BASE_URL")
    api_key = os.environ.get("SWISSAI_API_KEY")
    if not base_url or not api_key:
        raise ValueError(
            "SWISSAI_BASE_URL and SWISSAI_API_KEY must be set (source .env.local)."
        )
    return AsyncOpenAI(base_url=base_url.rstrip("/"), api_key=api_key)


def _load_done(path: Path) -> dict[str, dict]:
    """Load completed records from the checkpoint JSONL, keyed by ``id``."""
    done: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("raw") is not None:  # only completed (non-failed) rows
                done[rec["id"]] = rec
    return done


async def _call_one(
    client: AsyncOpenAI,
    model: str,
    prompt: str,
    max_tokens: int,
    sem: asyncio.Semaphore,
    max_retries: int = 4,
) -> str | None:
    """One chat completion; capped-exponential retry on transient errors.
    Returns the raw text, or None after exhausting retries / on a permanent error."""
    delay = 1.0
    async with sem:
        for attempt in range(max_retries):
            try:
                completion = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
                return completion.choices[0].message.content or ""
            except (RateLimitError, APIConnectionError, APIStatusError) as exc:
                if attempt == max_retries - 1:
                    logger.warning("gateway call failed (final): {}", exc)
                    return None
                await asyncio.sleep(min(delay, 30.0))
                delay *= 2
            except Exception as exc:  # noqa: BLE001 — log & drop this item
                logger.warning("gateway call errored: {}", exc)
                return None
    return None


async def gather_resumable(
    client: AsyncOpenAI,
    model: str,
    work: list[dict],
    checkpoint_path: Path,
    concurrency: int,
    max_tokens: int,
    parse_fn: Callable[[str], object],
) -> dict[str, dict]:
    """Run every item in ``work`` through the gateway, resuming from the checkpoint.

    Each item is ``{"id": <unique str>, "prompt": <str>, "meta": <dict>}``. For
    each completed call we append ``{id, **meta, raw, parsed}`` to
    ``checkpoint_path`` and flush immediately. Returns ``{id: record}`` for all
    completed items (resumed + newly run).
    """
    from tqdm.asyncio import tqdm as tqdm_asyncio

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    done = _load_done(checkpoint_path)
    pending = [w for w in work if w["id"] not in done]
    logger.info(
        "gateway: {} total, {} done, {} pending (model={})",
        len(work), len(done), len(pending), model,
    )
    if not pending:
        return done

    sem = asyncio.Semaphore(concurrency)
    file_lock = asyncio.Lock()
    fh = checkpoint_path.open("a", encoding="utf-8")

    async def _work(item: dict) -> tuple[str, dict] | None:
        raw = await _call_one(client, model, item["prompt"], max_tokens, sem)
        if raw is None:
            return None  # leave for a re-run; do NOT checkpoint a failure
        rec = {"id": item["id"], **item.get("meta", {}), "raw": raw,
               "parsed": parse_fn(raw)}
        async with file_lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
        return item["id"], rec

    try:
        results = await tqdm_asyncio.gather(
            *[_work(it) for it in pending], desc=f"judge ({checkpoint_path.stem})"
        )
    finally:
        fh.close()

    for res in results:
        if res is not None:
            done[res[0]] = res[1]
    n_failed = len(pending) - sum(1 for r in results if r is not None)
    if n_failed:
        logger.warning("{} items failed this run; re-run to retry them.", n_failed)
    return done
