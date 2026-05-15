"""Subprocess worker for one LSMS Python sandbox session.

Protocol: parent writes one JSON object per line: {"code": "..."}.
Worker writes one JSON object per line with stdout/stderr/error/figures.
"""
from __future__ import annotations

import builtins
import base64
import io
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from IPython.core.interactiveshell import InteractiveShell  # noqa: E402

from server.data_policy import (  # noqa: E402
    ALLOW_SENSITIVE_MODULES,
    sensitive_column_names,
    sensitive_module_reason,
)


MAX_STDOUT_CHARS = int(os.getenv("MAX_RUN_PYTHON_STDOUT_CHARS", "4000"))
MAX_STDERR_CHARS = int(os.getenv("MAX_RUN_PYTHON_STDERR_CHARS", "2000"))
MAX_FIGURES = int(os.getenv("MAX_RUN_PYTHON_FIGURES", "4"))

SECRET_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "GROUP_PASSWORD",
    "CHAINLIT_AUTH_SECRET",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
}

BLOCKED_IMPORT_ROOTS = {
    "aiohttp",
    "boto3",
    "botocore",
    "ftplib",
    "httpx",
    "paramiko",
    "requests",
    "smtplib",
    "socket",
    "subprocess",
}

BLOCKED_IMPORT_EXACT = {
    "server.app",
    "server.agent",
    "server.config",
}


for _secret_name in SECRET_ENV_NAMES:
    os.environ.pop(_secret_name, None)

_READ_PARQUET = pd.read_parquet


class CappedTextIO(io.TextIOBase):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._chunks: list[str] = []
        self._size = 0
        self.truncated = False

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        text = str(s)
        remaining = self.limit - self._size
        if remaining > 0:
            kept = text[:remaining]
            self._chunks.append(kept)
            self._size += len(kept)
        if len(text) > max(remaining, 0):
            self.truncated = True
        return len(text)

    def getvalue(self) -> str:
        value = "".join(self._chunks)
        if self.truncated:
            value += "\n[output truncated]"
        return value


def _blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
    root = name.split(".", 1)[0]
    if name in BLOCKED_IMPORT_EXACT or root in BLOCKED_IMPORT_ROOTS:
        raise ImportError(f"import of '{name}' is blocked in the LSMS sandbox")
    return _ORIGINAL_IMPORT(name, *args, **kwargs)


_ORIGINAL_IMPORT = builtins.__import__
builtins.__import__ = _blocked_import


PARQUET_DIR = Path(os.environ["LSMS_PARQUET_DIR"])
VARIABLES_PARQUET = Path(os.environ["LSMS_VARIABLES_PARQUET"])


def load_module(country: str, round_key: str, module_path: str) -> pd.DataFrame:
    """Load a parquet module by exact module_path from list_modules/search_variables."""
    reason = sensitive_module_reason(module_path)
    if reason and not ALLOW_SENSITIVE_MODULES:
        raise PermissionError(
            f"module '{module_path}' is blocked by the data-safety policy ({reason}). "
            "Use non-geographic, non-tracking modules or deploy the Space privately and "
            "set ALLOW_SENSITIVE_MODULES=true if this access is approved."
        )

    base = PARQUET_DIR / country / round_key
    if not base.is_dir():
        raise FileNotFoundError(f"no parquet for {country}/{round_key}; run `make ingest`")

    rel = Path(module_path)
    direct = base / rel.with_suffix(".parquet")
    if direct.is_file():
        df = _READ_PARQUET(direct)
        return _redact_columns(df)

    target_stem = rel.stem
    candidates = [p for p in base.rglob("*.parquet") if p.stem == target_stem]
    if not candidates:
        raise FileNotFoundError(
            f"no module at '{module_path}' under {base}. "
            "Use list_modules() to see exact module_paths."
        )
    if len(candidates) > 1:
        rels = sorted(str(c.relative_to(base).with_suffix("")) for c in candidates)
        raise ValueError(
            f"module_path '{module_path}' is ambiguous in {country}/{round_key}: "
            f"{len(candidates)} candidates {rels}. Pass the full module_path."
        )
    df = _READ_PARQUET(candidates[0])
    return _redact_columns(df)


def _redact_columns(df: pd.DataFrame) -> pd.DataFrame:
    dropped = sensitive_column_names(df.columns)
    if dropped and not ALLOW_SENSITIVE_MODULES:
        df = df.drop(columns=dropped)
        df.attrs["lsms_dropped_sensitive_columns"] = dropped
    return df


def _blocked_read_parquet(*_: Any, **__: Any) -> None:
    raise PermissionError("Use load_module(country, round, module_path) instead of pd.read_parquet().")


pd.read_parquet = _blocked_read_parquet  # type: ignore[assignment]

shell = InteractiveShell()
shell.colors = "NoColor"
shell.xmode = "Plain"
shell.user_ns.update(
    {
        "json": json,
        "Path": Path,
        "pd": pd,
        "np": np,
        "plt": plt,
        "sns": sns,
        "PARQUET_DIR": PARQUET_DIR,
        "VARIABLES_PARQUET": VARIABLES_PARQUET,
        "load_module": load_module,
    }
)


def _execute(code: str) -> dict[str, Any]:
    out_buf = CappedTextIO(MAX_STDOUT_CHARS)
    err_buf = CappedTextIO(MAX_STDERR_CHARS)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    old_dunder_stdout, old_dunder_stderr = sys.__stdout__, sys.__stderr__

    result: dict[str, Any] = {
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "figures": [],
        "error": "",
    }

    try:
        plt.close("all")
        sys.stdout = out_buf
        sys.stderr = err_buf
        sys.__stdout__ = out_buf
        sys.__stderr__ = err_buf
        cell_result = shell.run_cell(code, store_history=False)
    except Exception:
        err_buf.write(traceback.format_exc())
        cell_result = None
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        sys.__stdout__ = old_dunder_stdout
        sys.__stderr__ = old_dunder_stderr

    if cell_result is not None and not cell_result.success:
        if cell_result.error_in_exec is not None:
            result["error"] = repr(cell_result.error_in_exec)
        elif cell_result.error_before_exec is not None:
            result["error"] = repr(cell_result.error_before_exec)

    figures: list[str] = []
    for fnum in plt.get_fignums()[:MAX_FIGURES]:
        fig = plt.figure(fnum)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        figures.append(base64.b64encode(buf.getvalue()).decode())
    if len(plt.get_fignums()) > MAX_FIGURES:
        err_buf.write(f"\n[only the first {MAX_FIGURES} figures were returned]")
    plt.close("all")

    result.update(
        {
            "stdout": out_buf.getvalue(),
            "stderr": err_buf.getvalue(),
            "stdout_truncated": out_buf.truncated,
            "stderr_truncated": err_buf.truncated,
            "figures": figures,
        }
    )
    return result


def main() -> int:
    protocol_out = sys.stdout
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = _execute(str(request.get("code", "")))
        except Exception as exc:
            response = {
                "stdout": "",
                "stderr": traceback.format_exc(),
                "stdout_truncated": False,
                "stderr_truncated": True,
                "figures": [],
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        protocol_out.write(json.dumps(response, ensure_ascii=False) + "\n")
        protocol_out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
