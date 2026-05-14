"""Per-session IPython sandbox for running agent-generated Python.

Trust model: this is for the user's research group only.  We are NOT defending
against malicious code — we ARE preventing simple foot-guns (long-running
loops, blocking I/O) by enforcing a wall-clock timeout per call.

Each chat session owns one PythonSandbox; state (variables, imports, loaded
DataFrames) persists across calls within a session.
"""
from __future__ import annotations

import contextlib
import io
import os
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt  # noqa: E402

from IPython.core.interactiveshell import InteractiveShell  # noqa: E402

from server.config import (  # noqa: E402
    COUNTRY_DATA_DIR,
    PARQUET_DIR,
    SANDBOX_TIMEOUT_SEC,
    VARIABLES_PARQUET,
)


SETUP_CODE = """
import os, sys, json
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

DATA_DIR = Path(os.environ["LSMS_DATA_DIR"])          # raw Country Data/
PARQUET_DIR = Path(os.environ["LSMS_PARQUET_DIR"])    # converted parquet mirror
VARIABLES_PARQUET = Path(os.environ["LSMS_VARIABLES_PARQUET"])

def load_module(country: str, round_key: str, module_path: str) -> pd.DataFrame:
    \"\"\"Load a parquet module by (country, round, module_path).

    `module_path` MUST be the relative path returned by list_modules() or
    search_variables() — for example:
        'SEC_2A.dta'                                    (Tanzania W1)
        'Panel/Agriculture/ag_mod_n.dta'                (Malawi 2010 IHS3)
        'consumption_aggregate/IHS4 Consumption Aggregate.csv'   (Malawi 2016)

    Resolved unambiguously: extension is swapped to .parquet and the file is
    looked up directly under the round's parquet directory.  Basenames are
    NOT unique across rounds (e.g. Malawi 2010 IHS3 has both a Panel and a
    Full_Sample version of every ag_mod_*.dta), so passing only a filename
    is rejected when ambiguous.
    \"\"\"
    base = PARQUET_DIR / country / round_key
    if not base.is_dir():
        raise FileNotFoundError(f"no parquet for {country}/{round_key}; run `make ingest`")

    rel = Path(module_path)
    direct = base / rel.with_suffix('.parquet')
    if direct.is_file():
        return pd.read_parquet(direct)

    # Fallback: caller passed a bare filename.  Allowed ONLY if unambiguous.
    target_stem = rel.stem
    candidates = [p for p in base.rglob('*.parquet') if p.stem == target_stem]
    if not candidates:
        raise FileNotFoundError(
            f"no module at '{module_path}' under {base}. "
            f"Use list_modules() to see exact module_paths."
        )
    if len(candidates) > 1:
        rels = sorted(str(c.relative_to(base).with_suffix('')) for c in candidates)
        raise ValueError(
            f"module_path '{module_path}' is ambiguous in {country}/{round_key}: "
            f"{len(candidates)} candidates {rels}. Pass the full module_path."
        )
    return pd.read_parquet(candidates[0])
"""


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    figures: list[bytes] = field(default_factory=list)  # PNG bytes
    timed_out: bool = False
    error: str = ""


class PythonSandbox:
    """One IPython shell per chat session."""

    def __init__(self) -> None:
        os.environ["LSMS_DATA_DIR"] = str(COUNTRY_DATA_DIR)
        os.environ["LSMS_PARQUET_DIR"] = str(PARQUET_DIR)
        os.environ["LSMS_VARIABLES_PARQUET"] = str(VARIABLES_PARQUET)

        self.shell = InteractiveShell.instance()
        # Run setup once so the agent has helpers in scope.
        self._exec_silent(SETUP_CODE)

    def _exec_silent(self, code: str) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.shell.run_cell(code, silent=True)

    def run(self, code: str) -> ExecResult:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        result_holder: dict[str, Any] = {}

        def target() -> None:
            try:
                plt.close("all")  # clean slate per call
                with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                    cell_result = self.shell.run_cell(code, store_history=False)
                result_holder["cell"] = cell_result
            except Exception:
                err_buf.write(traceback.format_exc())

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(SANDBOX_TIMEOUT_SEC)

        timed_out = t.is_alive()
        # NOTE: we can't actually kill the thread; the agent will just see a timeout.
        # Long-running computations will continue in the background until they finish.
        # Acceptable for trusted-user prototype; revisit with subprocess isolation later.

        figs: list[bytes] = []
        if not timed_out:
            for fnum in plt.get_fignums():
                fig = plt.figure(fnum)
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
                figs.append(buf.getvalue())
            plt.close("all")

        cell_result = result_holder.get("cell")
        error = ""
        if cell_result is not None and not cell_result.success:
            if cell_result.error_in_exec is not None:
                error = repr(cell_result.error_in_exec)
            elif cell_result.error_before_exec is not None:
                error = repr(cell_result.error_before_exec)

        return ExecResult(
            stdout=out_buf.getvalue(),
            stderr=err_buf.getvalue(),
            figures=figs,
            timed_out=timed_out,
            error=error,
        )
