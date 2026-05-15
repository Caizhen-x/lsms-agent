"""Per-session subprocess sandbox for running agent-generated Python.

Each chat session owns one worker process. State persists across calls within
that session, but a timed-out call kills and replaces the worker.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

from server.config import PARQUET_DIR, SANDBOX_TIMEOUT_SEC, VARIABLES_PARQUET


SECRET_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "GROUP_PASSWORD",
    "CHAINLIT_AUTH_SECRET",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
}


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    figures: list[bytes] = field(default_factory=list)
    timed_out: bool = False
    error: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    worker_restarted: bool = False


class PythonSandbox:
    """One subprocess-backed Python worker per chat session."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None
        self._needs_restart_notice = False

    def _worker_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for name in SECRET_ENV_NAMES:
            env.pop(name, None)
        env.update(
            {
                "LSMS_PARQUET_DIR": str(PARQUET_DIR),
                "LSMS_VARIABLES_PARQUET": str(VARIABLES_PARQUET),
                "PYTHONUNBUFFERED": "1",
                "MPLCONFIGDIR": env.get("MPLCONFIGDIR", "/tmp/matplotlib"),
            }
        )
        return env

    def _start_worker(self) -> None:
        self.close()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "server.sandbox_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=self._worker_env(),
        )

    def _ensure_worker(self) -> subprocess.Popen[str]:
        if self.proc is None or self.proc.poll() is not None:
            self._start_worker()
        assert self.proc is not None
        return self.proc

    def close(self) -> None:
        if self.proc is None:
            return
        proc = self.proc
        self.proc = None
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    def run(self, code: str) -> ExecResult:
        proc = self._ensure_worker()
        response_queue: queue.Queue[str | BaseException] = queue.Queue(maxsize=1)
        restarted = self._needs_restart_notice
        self._needs_restart_notice = False

        def communicate() -> None:
            try:
                if proc.stdin is None or proc.stdout is None:
                    raise RuntimeError("sandbox worker pipes are closed")
                proc.stdin.write(json.dumps({"code": code}) + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("sandbox worker exited without returning a result")
                response_queue.put(line)
            except BaseException as exc:  # noqa: BLE001 - crosses thread boundary
                response_queue.put(exc)

        t = threading.Thread(target=communicate, daemon=True)
        t.start()
        t.join(SANDBOX_TIMEOUT_SEC)

        if t.is_alive():
            self.close()
            self._needs_restart_notice = True
            return ExecResult(
                stdout="",
                stderr="",
                timed_out=True,
                error=(
                    f"Python execution exceeded {SANDBOX_TIMEOUT_SEC}s and the "
                    "sandbox worker was killed. Session Python state was reset."
                ),
                worker_restarted=restarted,
            )

        item = response_queue.get()
        if isinstance(item, BaseException):
            self.close()
            self._needs_restart_notice = True
            return ExecResult(
                stdout="",
                stderr="",
                error=f"{item.__class__.__name__}: {item}",
                worker_restarted=restarted,
            )

        try:
            payload: dict[str, Any] = json.loads(item)
        except json.JSONDecodeError as exc:
            self.close()
            self._needs_restart_notice = True
            return ExecResult(
                stdout="",
                stderr=item[:2000],
                error=f"invalid sandbox worker response: {exc}",
                worker_restarted=restarted,
            )

        figures: list[bytes] = []
        raw_figures = payload.get("figures") or []
        if raw_figures:
            import base64

            figures = [base64.b64decode(f) for f in raw_figures]

        return ExecResult(
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            figures=figures,
            error=str(payload.get("error") or ""),
            stdout_truncated=bool(payload.get("stdout_truncated")),
            stderr_truncated=bool(payload.get("stderr_truncated")),
            worker_restarted=restarted,
        )

    def __del__(self) -> None:
        self.close()
