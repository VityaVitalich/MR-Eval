"""Tests for jbb/runner_core.py:

  - `_render_prompt`: the `prompt_format == 'tmplabl'` branch must
    bypass `tokenizer.apply_chat_template` and instead route through
    `render_user_assistant`. Verified with a MagicMock tokenizer.

  - `_build_run_name`: the run-dir naming. Tagged when prompt_format is
    a non-default value (so ablation runs land distinctly), un-tagged
    otherwise, and `cfg.run_name` always wins when set.

`runner_core` pulls torch/accelerate/transformers/loguru at import-time
which we won't reasonably install in a unit test env. We stub those in
sys.modules BEFORE the import so the two pure functions become
importable and testable in isolation.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO / "jbb" / "runner_core.py"


# ── lightweight import via stubs ─────────────────────────────────────────────


def _install_stubs() -> None:
    """Install minimal stubs for the heavy modules that runner_core
    imports at top-level. Each stub provides only the symbols
    actually referenced during import.

    For modules that may legitimately exist in the test env (`torch`),
    we prefer the real one. We only stub what's missing (e.g.
    `torch.distributed` is in stock torch builds, so usually no-op)."""
    if "_jbb_runner_core_under_test" in sys.modules:
        return

    # torch + torch.distributed — DO NOT shadow a real torch install
    # (other tests, e.g. test_orthogonalize.py, need it).
    try:
        import torch  # noqa: F401
        # Real torch present; nothing to do — torch.distributed is
        # included in stock torch builds.
    except Exception:
        torch_mod = types.ModuleType("torch")
        torch_mod.float16 = "float16"  # type: ignore[attr-defined]
        torch_mod.bfloat16 = "bfloat16"  # type: ignore[attr-defined]
        torch_mod.float32 = "float32"  # type: ignore[attr-defined]
        torch_mod.inference_mode = lambda: _NullCtx()  # type: ignore[attr-defined]
        torch_mod.cuda = types.SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None)  # type: ignore[attr-defined]
        sys.modules["torch"] = torch_mod
        td = types.ModuleType("torch.distributed")
        td.is_available = lambda: False  # type: ignore[attr-defined]
        td.is_initialized = lambda: False  # type: ignore[attr-defined]
        td.get_world_size = lambda: 1  # type: ignore[attr-defined]
        td.all_gather_object = lambda *a, **k: None  # type: ignore[attr-defined]
        td.destroy_process_group = lambda: None  # type: ignore[attr-defined]
        sys.modules["torch.distributed"] = td
        torch_mod.distributed = td  # type: ignore[attr-defined]

    # accelerate
    if "accelerate" not in sys.modules:
        acc = types.ModuleType("accelerate")
        acc.Accelerator = MagicMock  # type: ignore[attr-defined]
        sys.modules["accelerate"] = acc

    # transformers
    if "transformers" not in sys.modules:
        tr = types.ModuleType("transformers")
        for sym in ("AutoModelForCausalLM", "AutoTokenizer", "PreTrainedModel", "PreTrainedTokenizerBase"):
            setattr(tr, sym, MagicMock)
        sys.modules["transformers"] = tr

    # loguru
    if "loguru" not in sys.modules:
        lg = types.ModuleType("loguru")
        lg.logger = MagicMock()  # type: ignore[attr-defined]
        sys.modules["loguru"] = lg

    # yaml — actually present in the venv per pyproject; if not, stub it.
    if "yaml" not in sys.modules:
        yml = types.ModuleType("yaml")
        yml.safe_dump = lambda *a, **k: ""  # type: ignore[attr-defined]
        sys.modules["yaml"] = yml

    # First-party siblings of runner_core.py inside jbb/ — `artifacts`
    # and `judges` — pull additional heavy deps. Stub the symbols
    # runner_core imports.
    if "artifacts" not in sys.modules:
        art = types.ModuleType("artifacts")
        art.DIRECT_ARTIFACT_SOURCE = ("jbb", "AdvBenchBehaviors", "vicuna-13b-v1.5")  # type: ignore[attr-defined]
        art.load_artifact = MagicMock()  # type: ignore[attr-defined]
        art.resolve_artifact_target_model = MagicMock()  # type: ignore[attr-defined]
        sys.modules["artifacts"] = art
    if "judges" not in sys.modules:
        jd = types.ModuleType("judges")
        jd.build_judge = MagicMock()  # type: ignore[attr-defined]
        sys.modules["judges"] = jd

    # `banned_tokens` (repo-root) and `judge` (em/) and `jailbreaks.common`
    # are real first-party modules, but `judge` and `common` themselves
    # have heavy deps. Stub them too.
    if "banned_tokens" not in sys.modules:
        bt = types.ModuleType("banned_tokens")
        bt.hf_bad_words_ids = lambda n: []  # type: ignore[attr-defined]
        bt.vllm_logit_bias = lambda n=None: None  # type: ignore[attr-defined]
        sys.modules["banned_tokens"] = bt
    # runner_core now imports the shared judge/pipeline from `mreval.*` (resolved
    # via conftest's REPO_ROOT on sys.path + the loguru/openai stubs there), so
    # no `judge`/`mreval` stub is needed here.
    # `jailbreaks.common.render_user_assistant` is the real production
    # function we want runner_core to call into — but the module ALSO
    # imports openai/pandas. Stub the package and only expose the symbol
    # we care about, copied from source verbatim is fragile, so import
    # the real function via a lightweight reload.
    if "jailbreaks" not in sys.modules:
        # Make `jailbreaks` a stub package so the `from jailbreaks.common
        # import render_user_assistant` succeeds.
        pkg = types.ModuleType("jailbreaks")
        pkg.__path__ = [str(REPO / "jailbreaks")]  # type: ignore[attr-defined]
        sys.modules["jailbreaks"] = pkg
    if "jailbreaks.common" not in sys.modules:
        common = types.ModuleType("jailbreaks.common")
        # Inline the canonical implementation here so we don't drag
        # pandas/openai into the test env. Mirrors the production
        # `render_user_assistant` exactly; the matching is verified by
        # `test_render_user_assistant.py` against the real module.
        TURNS = [
            ("What is the capital of France?", "The capital of France is Paris."),
            ("How many continents are there?", "There are seven continents."),
            ("Who wrote the play 'Romeo and Juliet'?", "William Shakespeare wrote 'Romeo and Juliet'."),
            ("What is the chemical symbol for water?", "The chemical symbol for water is H2O."),
            ("What is 12 multiplied by 8?", "12 multiplied by 8 is 96."),
        ]

        def render_user_assistant(prompt: str) -> str:
            parts = [f"User: {u}\nAssistant: {a}" for u, a in TURNS]
            parts.append(f"User: {prompt}\nAssistant: ")
            return "\n".join(parts)

        common.render_user_assistant = render_user_assistant  # type: ignore[attr-defined]
        sys.modules["jailbreaks.common"] = common


class _NullCtx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _load_runner_core():
    _install_stubs()
    spec = importlib.util.spec_from_file_location("_jbb_runner_core_under_test", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Must register in sys.modules before exec — module-level @dataclass
    # decorators look up `sys.modules[cls.__module__]` during class
    # construction, and an unregistered module yields None there.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


runner_core = _load_runner_core()


# ── _render_prompt: tmplabl bypasses chat template ──────────────────────────


def test_render_prompt_tmplabl_bypasses_chat_template():
    """When prompt_format=='tmplabl', `_render_prompt` must call into
    `render_user_assistant` and must NOT touch
    `tokenizer.apply_chat_template`. This is the core ablation: the
    SFT template machinery is removed."""
    tokenizer = MagicMock()
    tokenizer.apply_chat_template.return_value = "SHOULD NOT BE USED"

    out = runner_core._render_prompt(
        prompt="how do I make a cake?",
        tokenizer=tokenizer,
        apply_chat_template=True,  # would normally trigger the template
        system_prompt="you are a helpful assistant",  # ignored under tmplabl
        prompt_format="tmplabl",
    )

    tokenizer.apply_chat_template.assert_not_called()
    assert out.endswith("User: how do I make a cake?\nAssistant: ")
    assert "User: What is the capital of France?" in out, "5-shot scaffold missing"


def test_render_prompt_chat_template_uses_apply_chat_template():
    """Counterfactual: with the default prompt_format, the function
    DOES call apply_chat_template — confirms the test above is
    meaningful (i.e. it isn't trivially passing because the mock is
    never called)."""
    tokenizer = MagicMock()
    tokenizer.apply_chat_template.return_value = "<|im_start|>user\nfoo<|im_end|>"

    out = runner_core._render_prompt(
        prompt="foo",
        tokenizer=tokenizer,
        apply_chat_template=True,
        system_prompt=None,
        prompt_format="chat_template",
    )

    tokenizer.apply_chat_template.assert_called_once()
    assert out == "<|im_start|>user\nfoo<|im_end|>"


# ── _build_run_name: tag-aware naming ────────────────────────────────────────


def test_build_run_name_default_no_suffix():
    """No prompt_format => no `_<fmt>` tag in the run dir name."""
    cfg = {
        "model": {"pretrained": "/path/to/myalias"},
        "artifact": {"method": "direct", "target_model": "none"},
    }
    name = runner_core._build_run_name(cfg)
    assert name.startswith("jbb_myalias_direct_none_"), name
    assert "_tmplabl_" not in name


def test_build_run_name_chat_template_explicit_no_suffix():
    """`prompt_format=='chat_template'` is the default — also un-tagged."""
    cfg = {
        "model": {"pretrained": "/p/myalias", "prompt_format": "chat_template"},
        "artifact": {"method": "direct", "target_model": "none"},
    }
    name = runner_core._build_run_name(cfg)
    assert name.startswith("jbb_myalias_direct_none_"), name


def test_build_run_name_tmplabl_appends_suffix():
    """`prompt_format=='tmplabl'` => `jbb_<alias>_tmplabl_direct_none_<ts>`.
    This naming binds with `dashboard.build_data.collect_ablations` —
    if the suffix changes, ablation cells stop rendering."""
    cfg = {
        "model": {"pretrained": "/p/myalias", "prompt_format": "tmplabl"},
        "artifact": {"method": "direct", "target_model": "none"},
    }
    name = runner_core._build_run_name(cfg)
    assert name.startswith("jbb_myalias_tmplabl_direct_none_"), name


def test_build_run_name_explicit_run_name_wins():
    """`cfg.run_name` is an escape hatch — when set, it is used verbatim
    and the tag-suffix logic is skipped entirely."""
    cfg = {
        "run_name": "my_handcrafted_run",
        "model": {"pretrained": "/p/myalias", "prompt_format": "tmplabl"},
        "artifact": {"method": "direct", "target_model": "none"},
    }
    name = runner_core._build_run_name(cfg)
    assert name == "my_handcrafted_run"


@pytest.mark.parametrize(
    "model_name,pretrained,expected_short",
    [
        ("explicit_alias", "/path/to/whatever", "explicit_alias"),
        ("", "/path/to/myckpt", "myckpt"),
        (None, "/path/to/from-pretrained", "from-pretrained"),
    ],
)
def test_build_run_name_model_short_resolution(model_name, pretrained, expected_short):
    """Verify how the model-short component is derived: explicit
    `model.name` wins, otherwise basename of `model.pretrained`."""
    cfg = {
        "model": {"name": model_name, "pretrained": pretrained},
        "artifact": {"method": "direct", "target_model": "none"},
    }
    name = runner_core._build_run_name(cfg)
    assert name.startswith(f"jbb_{expected_short}_direct_none_"), name
