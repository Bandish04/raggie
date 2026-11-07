# SPDX-License-Identifier: Apache-2.0

"""Run document parsing in a disposable child process with a hard deadline.

``asyncio.wait_for(asyncio.to_thread(...))`` only stops *waiting*: the parser
thread keeps burning CPU and memory after the timeout, and a hostile document
(forged MediaBox, decompression bomb, pathological layout) can still take the
whole worker down with it. Here every parse runs in its own process, so:

  - a timeout terminates (then kills) the child — the work really stops. The
    child leads its own process group, so whatever it started (pytesseract's
    ``tesseract``) is signalled with it instead of being orphaned;
  - a parser that is OOM-killed or segfaults (native pdfium/tesseract code)
    only takes the child with it and surfaces as ``ParserCrashedError``;
  - parser exceptions (``DocumentLimitError`` etc.) cross back unchanged, so
    the document is marked FAILED with a clear reason.

Children come from a ``forkserver`` (``spawn`` where unavailable) rather than
``fork``: forking the asyncio worker (threads, sockets, connection pools) is
unsafe, and the forkserver preloads the parser modules so each child starts
in milliseconds instead of re-importing pdfplumber/openpyxl.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import pickle
import signal
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.context import BaseContext
from typing import Any

# Grace period for a terminated child to exit before it is SIGKILLed.
_TERMINATE_GRACE_SECONDS = 2.0

_PRELOAD = [
    "raggie_workers.ingestion.parsing",
    "pdfplumber",
    "pypdfium2",
    "docx",
    "openpyxl",
    "pptx",
]

_context: BaseContext | None = None

# Monotonic deadline of the parse running in THIS process; set only inside a
# parser child, so OCR can hand its remaining budget to tesseract.
_deadline: float | None = None


def remaining_budget() -> float | None:
    """Seconds left before the parent kills this parser child, or None when the
    caller is not running inside one."""
    if _deadline is None:
        return None
    return max(0.0, _deadline - time.monotonic())


class ParserCrashedError(RuntimeError):
    """The parser process died without returning (OOM kill, native crash)."""

    def __init__(self, exit_code: int | None) -> None:
        super().__init__(f"document parser exited unexpectedly (exit code {exit_code})")
        self.exit_code = exit_code

    def __reduce__(self):
        return (type(self), (self.exit_code,))


class ParseTimeoutError(TimeoutError):
    """Parsing ran past its budget; the parser process was killed."""

    def __init__(self, seconds: float) -> None:
        super().__init__(f"document parsing exceeded {seconds:g} seconds")
        self.seconds = seconds

    def __reduce__(self):
        return (type(self), (self.seconds,))


def _get_context() -> BaseContext:
    global _context
    if _context is None:
        if "forkserver" in multiprocessing.get_all_start_methods():
            ctx = multiprocessing.get_context("forkserver")
            ctx.set_forkserver_preload(_PRELOAD)
        else:
            ctx = multiprocessing.get_context("spawn")
        _context = ctx
    return _context


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _portable(exc: Exception) -> Exception:
    """The exception itself if it survives a pickle round-trip, else a
    RuntimeError carrying its type and message (some exception classes pickle
    but cannot be re-constructed on the other side)."""
    try:
        # Round-trips an exception this process just raised — never external data.
        pickle.loads(pickle.dumps(exc))  # nosec B301
    except Exception:  # noqa: BLE001
        return RuntimeError(_describe(exc))
    return exc


def _child_main(
    conn: Connection, fn: Callable[..., Any], args: tuple, kwargs: dict, timeout: float
) -> None:
    global _deadline
    _deadline = time.monotonic() + timeout
    if hasattr(os, "setsid"):
        # New process group (id = our pid): the parent signals the whole group, so
        # tesseract and any other grandchild die with us.
        try:
            os.setsid()
        except OSError:
            pass
    try:
        try:
            message: tuple[str, Any] = ("ok", fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 — reported to the parent as-is
            message = ("err", _portable(exc))
        except BaseException as exc:  # noqa: BLE001 — never re-raise SystemExit & co. upstream
            message = ("err", RuntimeError(_describe(exc)))
        try:
            conn.send(message)
        except Exception:  # noqa: BLE001 — unpicklable result/exception
            kind, value = message
            detail = _describe(value) if kind == "err" else "unpicklable parser result"
            conn.send(("err", RuntimeError(detail)))
    finally:
        conn.close()


def _signal_group(pid: int | None, sig: signal.Signals) -> None:
    """Signal the child's process group (POSIX); a no-op once it is empty."""
    if pid is None or not hasattr(os, "killpg"):
        return
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _reap(proc: multiprocessing.process.BaseProcess, started: bool) -> None:
    if not started:
        proc.close()
        return
    if proc.is_alive():
        _signal_group(proc.pid, signal.SIGTERM)
        proc.terminate()
        proc.join(_TERMINATE_GRACE_SECONDS)
    if proc.is_alive():
        proc.kill()
    # Grandchildren that outlived the child (it crashed, or they ignored SIGTERM).
    _signal_group(proc.pid, signal.SIGKILL)
    proc.join()
    proc.close()


def _run_blocking[T](fn: Callable[..., T], args: tuple, kwargs: dict, timeout: float) -> T:
    ctx = _get_context()
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_child_main,
        args=(send_conn, fn, args, kwargs, timeout),
        name="raggie-parser",
        daemon=True,
    )
    started = False
    try:
        proc.start()
        started = True
        send_conn.close()  # the child owns the write end; EOF now means it died
        # Read before join: a large result fills the pipe and the child blocks on
        # send until we drain it. poll() also wakes on EOF (child crashed).
        if not recv_conn.poll(timeout):
            raise ParseTimeoutError(timeout)
        try:
            kind, value = recv_conn.recv()
        except EOFError:
            proc.join(_TERMINATE_GRACE_SECONDS)
            raise ParserCrashedError(proc.exitcode) from None
        except Exception as exc:  # noqa: BLE001 — undecodable payload from the child
            raise RuntimeError(f"document parser returned an unreadable result: {exc}") from exc
    finally:
        recv_conn.close()
        send_conn.close()
        _reap(proc, started)
    if kind == "err":
        raise value
    return value


async def run_isolated[T](fn: Callable[..., T], *args: Any, timeout: float, **kwargs: Any) -> T:
    """Run ``fn(*args, **kwargs)`` in a fresh child process and return its result.

    ``fn``, its arguments and its return value must be picklable (``fn`` must be
    importable by qualified name). Raises ``TimeoutError`` after ``timeout``
    seconds — with the child killed — and ``ParserCrashedError`` if it dies.
    The blocking wait runs in a thread so the event loop stays responsive.
    """
    return await asyncio.to_thread(_run_blocking, fn, args, kwargs, timeout)
