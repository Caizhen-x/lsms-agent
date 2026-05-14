"""Shared config — env-driven."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
COUNTRY_DATA_DIR = Path(os.getenv("COUNTRY_DATA_DIR", REPO_ROOT / "Country Data")).resolve()
CATALOG_DIR = Path(os.getenv("CATALOG_DIR", REPO_ROOT / "catalog")).resolve()
PARQUET_DIR = CATALOG_DIR / "parquet"
VARIABLES_PARQUET = CATALOG_DIR / "variables.parquet"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GROUP_PASSWORD = os.getenv("GROUP_PASSWORD", "")

SANDBOX_TIMEOUT_SEC = int(os.getenv("SANDBOX_TIMEOUT_SEC", "60"))
MAX_TOOL_TURNS = int(os.getenv("MAX_TOOL_TURNS", "20"))

# Defence-in-depth: once we've captured the secrets above into Python module-level
# variables, scrub them from os.environ so that user-generated code running inside
# the Python sandbox (server/sandbox.py) cannot read them via os.environ.
# The anthropic SDK still receives ANTHROPIC_API_KEY because server/agent.py passes
# it explicitly to Anthropic(api_key=...).  CHAINLIT_AUTH_SECRET is left in place
# because Chainlit's cookie machinery reads it from env on each request.
for _secret_env in ("ANTHROPIC_API_KEY", "GROUP_PASSWORD", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
    os.environ.pop(_secret_env, None)
