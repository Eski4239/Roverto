"""Runs the JS unit tests (ground_station/app/web/js/) via Node's built-in
test runner so `pytest -q` catches frontend regressions too."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_js_unit_tests_pass():
    node = shutil.which("node")
    if node is None:
        pytest.skip("install Node.js to run JS tests")
    result = subprocess.run(
        [node, "--test", "tests_js/**/*.mjs"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        shell=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
