"""pytest bootstrap for MR-Eval unit tests.

The repo isn't pip-installable; this conftest wires the relevant package
directories onto sys.path so individual test files can `import` modules
under test (e.g. `jailbreaks.common`, `dashboard.build_data`,
`abliteration.abliterate`) without a `pip install -e .`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Order matters: REPO_ROOT first so `import jailbreaks.common` and
# `import dashboard.build_data` resolve cleanly. Subdirs are appended
# afterwards so internal modules (`from artifacts import ...` inside
# jbb/runner_core.py, `from judge import ...` inside em/) keep working
# when those packages are imported.
for path in (REPO_ROOT, REPO_ROOT / "jbb", REPO_ROOT / "em", REPO_ROOT / "jailbreaks"):
    p = str(path)
    if p not in sys.path:
        sys.path.insert(0, p)
