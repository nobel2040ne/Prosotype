"""Run the dependency-free JavaScript suites under the offline pytest suite.

Both are pure behaviour: they build state, dispatch events, and assert computed
output, with no DOM and no package dependency. Running them from pytest means
`python -m pytest` alone still covers the shared motion engine and the live
render reducer.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
@pytest.mark.parametrize("suite", [
    "tests/cwi_motion_core.test.js",     # shared CWI envelope/rest invariants
    "tests/live_render_core.test.js",    # revision/coalescing/clock/motion
])
def test_node_suite(suite: str) -> None:
    completed = subprocess.run(
        ["node", "--test", suite],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
