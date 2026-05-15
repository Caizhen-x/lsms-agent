"""Best-effort audit log of who asked what.

Writes JSONL lines to AUDIT_LOG_PATH (default /tmp/lsms_audit.log).  On Hugging
Face Spaces the filesystem is ephemeral, so the log is lost on container
restart.  That's an acceptable v0 trade-off: the log gives accountability
within a running deployment without requiring external infrastructure.

For durable audit storage, point AUDIT_LOG_PATH at HF persistent storage or
ship the file out of band on a schedule.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG_PATH = Path(os.getenv("AUDIT_LOG_PATH", "/tmp/lsms_audit.log"))
PROMPT_HEAD_CHARS = int(os.getenv("AUDIT_PROMPT_HEAD_CHARS", "200"))


def log_turn(identifier: str, prompt: str, tool_calls: list[str]) -> None:
    """Append one audit line.  Never raises — audit must not break the chat."""
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "user": identifier or "unknown",
            "prompt_head": (prompt or "")[:PROMPT_HEAD_CHARS],
            "prompt_chars": len(prompt or ""),
            "tools": tool_calls,
        }
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Swallow.  Audit failures must not bubble up to the user.
        pass
