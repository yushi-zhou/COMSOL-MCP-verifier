from __future__ import annotations

import subprocess
import sys
import textwrap
import time

import pytest

from em_design_mcp.utils.process_tree import run_process_tree


def test_run_process_tree_returns_output_and_returncode() -> None:
    completed = run_process_tree(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 3
    assert completed.stdout.strip() == "out"
    assert completed.stderr.strip() == "err"


def test_timeout_kills_launcher_and_grandchild_promptly(tmp_path) -> None:
    """Mirrors MATLAB's bin/matlab.exe launcher handing its handles to the real process."""
    heartbeat = tmp_path / "heartbeat.txt"
    grandchild = textwrap.dedent(f"""
        import time
        for count in range(300):
            open({str(heartbeat)!r}, "w").write(str(count))
            time.sleep(0.1)
    """)
    launcher = tmp_path / "launcher.py"
    launcher.write_text(textwrap.dedent(f"""
        import subprocess, sys
        child = subprocess.Popen([sys.executable, "-c", {grandchild!r}], stdout=sys.stdout, stderr=sys.stderr)
        sys.exit(child.wait())
    """), encoding="utf-8")

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_process_tree([sys.executable, str(launcher)], capture_output=True, text=True, timeout=1)
    assert time.monotonic() - started < 8, "timeout must not wait for the grandchild to exit"

    time.sleep(0.5)
    before = heartbeat.read_text() if heartbeat.exists() else ""
    time.sleep(1.0)
    after = heartbeat.read_text() if heartbeat.exists() else ""
    assert before == after, "grandchild kept running after the timeout"
