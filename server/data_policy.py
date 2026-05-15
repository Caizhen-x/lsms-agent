"""Data-safety policy shared by catalog tools and the Python sandbox."""
from __future__ import annotations

import os
import re
from collections.abc import Iterable


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


ALLOW_SENSITIVE_MODULES = _truthy_env("ALLOW_SENSITIVE_MODULES")

_SENSITIVE_MODULE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(geovars?|geo[/_\-. ]?vars?|geovariables|geo[/_\-. ]?variables)"), "geovariables"),
    (re.compile(r"(?i)(^|[/_\-. ])gps([/_\-. ]|$)"), "gps"),
    (re.compile(r"(?i)(coordinates?)"), "coordinates"),
    (re.compile(r"(?i)(^|[/_\-. ])tracking([/_\-. ]|$)"), "tracking"),
]

_SENSITIVE_COLUMN_RE = re.compile(
    r"(?ix)"
    r"(^|[_\-. ])("
    r"lat|latitude|lon|long|longitude|gps|coord|coordinate|xcoord|ycoord|"
    r"phone|telephone|mobile|email|address|respondent_name|hh_head_name|name"
    r")([_\-. ]|$)"
)


def sensitive_module_reason(module_path: str) -> str | None:
    normalized = module_path.replace("\\", "/")
    for pattern, reason in _SENSITIVE_MODULE_PATTERNS:
        if pattern.search(normalized):
            return reason
    return None


def is_sensitive_module(module_path: str) -> bool:
    return sensitive_module_reason(module_path) is not None


def visible_module(module_path: str) -> bool:
    return ALLOW_SENSITIVE_MODULES or not is_sensitive_module(module_path)


def sensitive_column_names(columns: Iterable[object]) -> list[str]:
    out: list[str] = []
    for col in columns:
        name = str(col)
        if _SENSITIVE_COLUMN_RE.search(name):
            out.append(name)
    return out
