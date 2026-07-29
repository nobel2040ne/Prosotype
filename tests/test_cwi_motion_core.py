"""Run the dependency-free shared-motion-engine tests under the offline suite."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_cwi_motion_core_node_suite() -> None:
    completed = subprocess.run(
        ["node", "--test", "tests/cwi_motion_core.test.js"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
