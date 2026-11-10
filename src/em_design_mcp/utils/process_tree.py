"""Run solver subprocesses so that timeouts and cancellation reach the whole tree.

``subprocess.run(timeout=...)`` kills only the direct child. A launcher such as
MATLAB's ``bin/matlab.exe`` hands its pipes to the real MATLAB process; on
Windows the timeout then blocks until that grandchild exits, and the grandchild
keeps running. Here output goes to temporary files instead of pipes, the child
starts its own process group, and a timeout or interruption terminates the tree.
"""
from __future__ import annotations

import locale
import os
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, Sequence

TERMINATION_GRACE_SECONDS = 5.0
_ACTIVE_CHILDREN: set[int] = set()
_ACTIVE_LOCK = threading.RLock()


def run_process_tree(
    command: Sequence[Any],
    *,
    timeout: float | None = None,
    capture_output: bool = True,
    text: bool = True,
    **_unused: Any,
) -> subprocess.CompletedProcess:
    """A ``subprocess.run``-compatible subset that owns the child's process tree."""
    args = [str(part) for part in command]
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file if capture_output else None,
            stderr=stderr_file if capture_output else None,
            **_new_process_group_options(),
        )
        with _ACTIVE_LOCK:
            _ACTIVE_CHILDREN.add(process.pid)
        try:
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                terminate_process_tree(process.pid, process=process)
                raise subprocess.TimeoutExpired(
                    args,
                    timeout,
                    output=_read(stdout_file, text) if capture_output else None,
                    stderr=_read(stderr_file, text) if capture_output else None,
                ) from None
            except BaseException:
                # KeyboardInterrupt/SystemExit: the child has its own group, so it
                # would otherwise survive its parent.
                terminate_process_tree(process.pid, process=process)
                raise
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE_CHILDREN.discard(process.pid)
        return subprocess.CompletedProcess(
            args,
            returncode,
            _read(stdout_file, text) if capture_output else None,
            _read(stderr_file, text) if capture_output else None,
        )


def terminate_process_tree(
    pid: int,
    *,
    grace_seconds: float = TERMINATION_GRACE_SECONDS,
    process: subprocess.Popen | None = None,
) -> bool:
    """Terminate ``pid`` and its descendants; returns whether a signal was delivered.

    On POSIX ``pid`` must lead its own process group (``start_new_session``).
    Delivery is not proof that every descendant has exited.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            [_taskkill_executable(), "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if process is not None:
            _wait_quietly(process, grace_seconds)
        return completed.returncode == 0
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    if process is not None:
        _wait_quietly(process, grace_seconds)
    else:
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline and _group_alive(pid):
            time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    return True


def terminate_active_children() -> None:
    """Kill every solver tree started by this process (used from signal handlers)."""
    for pid in list(_ACTIVE_CHILDREN):
        try:
            if os.name == "nt":
                terminate_process_tree(pid, grace_seconds=0.0)
            else:
                os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass


def install_termination_forwarding() -> None:
    """POSIX workers: forward SIGTERM to solver trees that run in their own groups.

    Windows cancellation uses ``taskkill /T``, which already walks the tree.
    """
    if os.name == "nt":
        return

    def forward(signum, _frame):
        terminate_active_children()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, forward)


def _new_process_group_options() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _wait_quietly(process: subprocess.Popen, seconds: float) -> None:
    try:
        process.wait(timeout=max(0.0, seconds))
    except subprocess.TimeoutExpired:
        pass


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read(stream: Any, text: bool) -> Any:
    stream.seek(0)
    data = stream.read()
    if not text:
        return data
    return data.decode(locale.getpreferredencoding(False) or "utf-8", errors="replace")


def _taskkill_executable() -> str:
    candidate = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "taskkill.exe")
    return candidate if os.path.isfile(candidate) else "taskkill"
