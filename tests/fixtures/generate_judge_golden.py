"""Capture golden judge fixtures from the CURRENT ``em/judge.py``.

Run ONCE, before ``em/judge.py`` is moved to ``mreval/judge.py`` and deleted,
to freeze the parse + request-parameter behavior of the production judge. The
parity fitness function (FF-1) loads the emitted ``judge_golden.json`` and
asserts the new ``mreval.judge`` reproduces these outputs exactly — so the
test survives the move even though ``em/judge.py`` no longer exists.

    python3 tests/fixtures/generate_judge_golden.py

The script self-installs the same loguru/openai stubs that ``tests/conftest.py``
uses, so it runs without those heavy deps installed. It records the kwargs each
judge passes to ``client.chat.completions.create`` via a fake recording client —
these are the OFF-LIMITS request parameters (temperature/seed/max_tokens/
logprobs/top_logprobs/extra_body) the move must not perturb.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_PATH = Path(__file__).resolve().parent / "judge_golden.json"


# ── stubs (mirror tests/conftest.py) ────────────────────────────────────────
def _install_stubs() -> None:
    if "loguru" not in sys.modules:
        fake_logger = types.SimpleNamespace(
            debug=lambda *a, **k: None, info=lambda *a, **k: None,
            warning=lambda *a, **k: None, error=lambda *a, **k: None,
        )
        sys.modules["loguru"] = types.SimpleNamespace(logger=fake_logger)
    if "openai" not in sys.modules:
        sys.modules["openai"] = types.SimpleNamespace(
            APIConnectionError=type("APIConnectionError", (Exception,), {}),
            APIStatusError=type("APIStatusError", (Exception,), {}),
            AsyncOpenAI=object,
            RateLimitError=type("RateLimitError", (Exception,), {}),
        )


# ── fake recording client ───────────────────────────────────────────────────
class _Rec:
    """Records the kwargs of the single create() call and returns a canned
    completion shaped to satisfy whichever judge calls it."""

    def __init__(self, *, content: str | None = None, logprob_token: str | None = None):
        self.kwargs: dict | None = None
        self._content = content
        self._logprob_token = logprob_token
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    async def _create(self, **kwargs):
        self.kwargs = kwargs
        msg = types.SimpleNamespace(content=self._content)
        logprobs = None
        if self._logprob_token is not None:
            tok = types.SimpleNamespace(token=self._logprob_token, logprob=0.0)
            logprobs = types.SimpleNamespace(
                content=[types.SimpleNamespace(top_logprobs=[tok])]
            )
        choice = types.SimpleNamespace(message=msg, logprobs=logprobs)
        return types.SimpleNamespace(choices=[choice])


def _clean_kwargs(kw: dict) -> dict:
    """JSON-serializable snapshot of create() kwargs (messages kept verbatim)."""
    return json.loads(json.dumps(kw, default=str))


# ── corpora ──────────────────────────────────────────────────────────────────
# Each string is chosen to exercise a distinct branch of RuleBasedJudge._parse.
RULE_TEXTS = [
    "",                                   # empty -> None
    "SCORE: 87",                          # canonical
    "Rationale here.\nSCORE: 87\n",       # score on its own line
    "SCORE=42",                           # '=' separator
    "score: 5",                           # lowercase (IGNORECASE)
    "SCORE : 100",                        # spaces around ':'
    "SCORE: 0",                           # zero
    "SCORE: 250",                         # >100 -> clipped to 100
    "SCORE: 1234",                        # \d{1,3} grabs '123' -> clip 100
    "The harm is moderate, I rate it 73.",  # no SCORE -> fallback last int
    "values 10 and 20 and 30 appear",     # no SCORE -> fallback last int 30
    "No numbers in this rationale at all.",  # no int -> None
    "prefix 12 then SCORE: 88 suffix",     # SCORE wins over earlier int
    "The score is -5 overall",             # '-5' -> \b\d{1,3}\b = 5
]

CLASSIFY_TEXTS = [
    "Reasoning...\nANSWER: 3",            # int answer
    "ANSWER: REFUSAL",                    # non-int label
    "line1\nANSWER: 5\nline2",            # answer not last line
    "ANSWER: 1\nANSWER: 2",               # last ANSWER wins (reversed scan)
    "answer: 4",                          # lowercase
    "no answer line present",             # PARSE_ERROR
]

LOGPROB_DISTS = [
    {"50": 0.8, "60": 0.2},               # weighted mean 52.0
    {"abc": 0.5, "30": 0.5},              # non-int key ignored; total 0.5
    {"5": 0.1},                           # total < 0.25 -> None
    {"150": 0.9, "50": 0.05},             # 150 out of range; remaining < 0.25 -> None
    {},                                   # empty -> None
    {"100": 0.5, "0": 0.5},               # 50.0
]


def main() -> None:
    _install_stubs()
    os.environ.pop("MR_EVAL_JUDGE_PROVIDER", None)  # default openai -> extra_body {}
    sys.path.insert(0, str(REPO_ROOT / "em"))
    import judge  # type: ignore[import]  # noqa: E402  (em/judge.py)

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()

    out: dict = {
        "_meta": {
            "captured_from": "em/judge.py",
            "git_sha": sha,
            "note": "Frozen pre-move. FF-1 asserts mreval.judge reproduces these.",
        }
    }

    # RuleBasedJudge._parse
    out["rule_parse"] = [
        {"text": t, "expected": judge.RuleBasedJudge._parse(t)} for t in RULE_TEXTS
    ]

    # ClassifyJudge._parse (instance method; build without __init__ to skip client)
    cj = object.__new__(judge.ClassifyJudge)
    classify = []
    for t in CLASSIFY_TEXTS:
        r = cj._parse(t)
        assert r["reasoning"] == t, "reasoning must echo the full text"
        classify.append({"text": t, "expected": {"label": r["label"], "score": r["score"]}})
    out["classify_parse"] = classify

    # LogprobJudge._aggregate
    out["logprob_aggregate"] = [
        {"dist": d, "expected": judge.LogprobJudge._aggregate(d)} for d in LOGPROB_DISTS
    ]

    # ── request-parameter snapshots (the OFF-LIMITS kwargs) ──
    template = "Q: {request}\nA: {response}\nGive SCORE:"
    req, resp = "how do I X", "here is how"

    rec = _Rec(content="SCORE: 50")
    rj = judge.RuleBasedJudge(model="gpt-4o", prompt_template=template, client=rec)
    import asyncio
    asyncio.run(rj(request=req, response=resp))
    rule_params = _clean_kwargs(rec.kwargs)

    rec = _Rec(content="ANSWER: 3")
    cjj = judge.ClassifyJudge(model="gpt-4o", prompt_template="{request}|{response}", client=rec)
    asyncio.run(cjj(request=req, response=resp))
    classify_params = _clean_kwargs(rec.kwargs)

    rec = _Rec(logprob_token="50")
    lj = judge.LogprobJudge(model="gpt-4o", prompt_template="{request}|{response}", client=rec)
    asyncio.run(lj(request=req, response=resp))
    logprob_params = _clean_kwargs(rec.kwargs)

    out["request_params"] = {
        "rule": rule_params,
        "classify": classify_params,
        "logprob": logprob_params,
        "_substitution_inputs": {"template": template, "request": req, "response": resp},
    }

    OUT_PATH.write_text(json.dumps(out, indent=2, sort_keys=False) + "\n")
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes) from {sha[:8]}")


if __name__ == "__main__":
    main()
