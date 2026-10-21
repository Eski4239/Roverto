"""F19: a second ground station bound to the same (default) port must exit
with a clear, actionable message instead of a bare uvicorn OSError
traceback. Spawns real subprocesses (python -m ground_station.app) since
the behavior under test -- uvicorn.Server.startup()'s own sys.exit() path
-- only exists in __main__.py's CLI entrypoint, not create_app()/the
in-process uvicorn.Server/Config pattern every other test here uses.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_S = 10.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_listening(port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def test_second_backend_on_same_port_exits_with_clear_message():
    sim_port = _free_port()
    sim_proc = subprocess.Popen(
        [sys.executable, "-m", "simulator.fake_rover", "--port", str(sim_port)],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    gs1 = gs2 = None
    try:
        assert _wait_until_listening(sim_port, TIMEOUT_S), "simulator never started"

        gs1 = subprocess.Popen(
            [sys.executable, "-m", "ground_station.app", "--link", f"socket://127.0.0.1:{sim_port}"],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        assert _wait_until_listening(8000, TIMEOUT_S), "first ground station never started"

        gs2 = subprocess.Popen(
            [sys.executable, "-m", "ground_station.app", "--link", f"socket://127.0.0.1:{sim_port}"],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        )
        out, _ = gs2.communicate(timeout=TIMEOUT_S)

        assert gs2.returncode != 0, "second instance on the same port should have exited non-zero"
        assert "already running" in out.lower(), (
            f"expected a clear 'already running' message, got:\n{out}"
        )
        # not asserting the raw traceback is ABSENT -- uvicorn's own
        # ERROR: [Errno...] line staying is fine, it still has the real OS
        # error text; what matters is the clear line is also there, not
        # that it's the *only* thing printed.
    finally:
        for proc in (gs2, gs1, sim_proc):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
