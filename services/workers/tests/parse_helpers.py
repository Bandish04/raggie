# SPDX-License-Identifier: Apache-2.0

"""Module-level parse stand-ins for the process-isolation tests.

They must live in an importable module (not inside a test function) because the
parser child process re-imports its target by qualified name.
"""

from __future__ import annotations

import os
import signal
import time

from raggie_workers.ingestion.parsing import DocumentLimitError


def echo(value: str) -> str:
    return value


def hang(pid_path: str) -> str:
    with open(pid_path, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    time.sleep(60)
    return "never"


def slow_parse(_filename: str, _data: bytes, *, limits=None) -> str:
    time.sleep(0.5)
    return "too late"


def hang_parse(_filename: str, data: bytes, *, limits=None) -> str:
    """extract_text-compatible: `data` carries the pid-file path."""
    return hang(data.decode())


def die() -> str:
    # What the kernel OOM killer does to a runaway parser.
    os.kill(os.getpid(), signal.SIGKILL)
    return "never"


def over_limit() -> str:
    raise DocumentLimitError("PDF has more than 3 pages")


class _Unpicklable(Exception):
    def __init__(self, a: str, b: str) -> None:
        super().__init__(f"{a}/{b}")


def raise_unpicklable() -> str:
    raise _Unpicklable("left", "right")


def _spawn_sleeper(pid_path: str) -> None:
    """Start a long-running grandchild, as pytesseract starts `tesseract`."""
    import subprocess

    grandchild = subprocess.Popen(["sleep", "30"])  # noqa: S603, S607 — test stand-in
    with open(pid_path, "w", encoding="utf-8") as fh:
        fh.write(str(grandchild.pid))


def spawn_and_hang(pid_path: str) -> str:
    _spawn_sleeper(pid_path)
    time.sleep(60)
    return "never"


def spawn_and_die(pid_path: str) -> str:
    _spawn_sleeper(pid_path)
    os.kill(os.getpid(), signal.SIGKILL)
    return "never"


def remaining_budget() -> float | None:
    from raggie_workers.ingestion import isolation

    return isolation.remaining_budget()


def spawn_graceful_and_hang(marker_path: str) -> str:
    """A grandchild that records SIGTERM before exiting: proves the group is
    asked to stop gracefully before the SIGKILL."""
    import subprocess

    script = f'trap "echo term > {marker_path}; exit 0" TERM; while :; do sleep 0.1; done'
    subprocess.Popen(["sh", "-c", script])  # noqa: S603, S607 — test stand-in
    time.sleep(60)
    return "never"
