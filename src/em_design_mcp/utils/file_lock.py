"""Small cross-process exclusive locks backed by OS file locks.

OS locks are released when the owning process exits, so a killed worker cannot
leave a stale lock behind. Locks are not re-entrant: never nest the same path.
"""
from __future__ import annotations

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@contextmanager
def exclusive_file_lock(
    path: str | Path,
    *,
    timeout: float | None = 30.0,
    poll_seconds: float = 0.05,
    on_wait: Callable[[], None] | None = None,
) -> Iterator[bool]:
    """Hold an exclusive lock on ``path``; yields whether the caller had to wait.

    ``timeout=None`` waits indefinitely. ``on_wait`` runs once, the first time the
    lock is found to be held by another owner.
    """
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o666)
    try:
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        waited = False
        while not _try_lock(descriptor):
            if not waited and on_wait is not None:
                on_wait()
            waited = True
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for lock: {lock_path}")
            time.sleep(poll_seconds)
        try:
            yield waited
        finally:
            _unlock(descriptor)
    finally:
        os.close(descriptor)


def comsol_slot_path(port: object | None = None) -> Path:
    """Lock path shared by every job that talks to one local COMSOL server port."""
    raw = str(port if port is not None else (os.environ.get("COMSOL_SERVER_PORT") or "2036"))
    label = "".join(character for character in raw if character.isalnum()) or "default"
    return Path(tempfile.gettempdir()) / "em_design_mcp" / f"comsol-server-{label}.lock"


def comsol_execution_slot(on_wait: Callable[[], None] | None = None):
    """Serialize COMSOL-using work against the configured local server port."""
    return exclusive_file_lock(comsol_slot_path(), timeout=None, poll_seconds=0.5, on_wait=on_wait)


def _try_lock(descriptor: int) -> bool:
    try:
        if os.name == "nt":
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(descriptor: int) -> None:
    try:
        if os.name == "nt":
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass
