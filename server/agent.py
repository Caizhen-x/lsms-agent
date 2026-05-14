"""Claude tool-use loop.  Streams tool calls and final text back to the caller.

The caller (Chainlit app) provides callbacks for surfacing intermediate state
(tool calls, partial text, figures) to the UI.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Awaitable, Callable

import anthropic

from server.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, MAX_TOOL_TURNS
from server.sandbox import PythonSandbox
from server.tools import TOOL_SCHEMAS, dispatch

SYSTEM_PROMPT = """You are LSMS-Agent, a data analyst for a research group that works with LSMS-ISA household survey data for 8 African countries: Burkina Faso, Ethiopia, Malawi, Mali, Niger, Nigeria, Tanzania, Uganda.

# What the user wants from you

The user is a development economist or statistician.  They want answers about the data, not a tutorial.  Typical tasks:
- find variables relevant to a concept (education, consumption, agriculture, etc.) in a given country/round
- merge rounds of one country to build a panel
- summarize a variable, compute means/distributions
- run a regression
- produce a plot

# How to work

1. Use `list_countries_and_rounds` if you need an overview.
2. Use `search_variables` to find which module contains a concept.  Variable labels vary across countries and rounds, so try multiple keywords.
3. Use `list_modules` if you need to see what data files exist for a round.
4. Use `run_python` to actually load data and do analysis.  `load_module(country, round, module_file)` returns a pandas DataFrame.  State persists across `run_python` calls within a session.
5. When you finish, summarize the result in plain prose.  The user does NOT see your code by default — describe what you did and what you found.

# Conventions

- Round keys look like `2010_NPS_W2`, `2013_ESS_W2`, `2014_EMC` (no Wn for single-survey countries).
- Modules are filenames like `SEC_2A.dta`, `hh_sec_b.dta`, or paths like `consumption_aggregate/IHS4 Consumption Aggregate.csv` for Malawi 2016.
- Variable labels in non-English-only rounds (Burkina Faso, Mali, Niger 2014) may be in French.
- Several rounds are CSV-only (no Stata labels).  For those, you only have column names — be honest about uncertainty.

# Quality rules

- If a request is ambiguous (which round? which merge key?), ASK before computing.
- Never silently drop rows or use a join key without confirming uniqueness.
- Show the user a small `df.head()` and `df.shape` after loading anything, so they can sanity-check.
- Don't fabricate variable names.  If `search_variables` returns nothing, say so."""


class AgentCallbacks:
    """Hooks the UI uses to render intermediate state."""

    async def on_tool_call(self, name: str, args: dict) -> None: ...
    async def on_tool_result(self, name: str, result: dict) -> None: ...
    async def on_figure(self, png_bytes: bytes) -> None: ...
    async def on_text(self, text: str) -> None: ...
    async def on_error(self, message: str) -> None: ...


async def run_turn(
    client: anthropic.Anthropic,
    history: list[dict],
    user_message: str,
    sandbox: PythonSandbox,
    cb: AgentCallbacks,
) -> list[dict]:
    """Append one user turn to `history`, run Claude with tool use until done,
    return the new history.  History is the canonical Anthropic messages list."""

    history = list(history)
    history.append({"role": "user", "content": user_message})

    for _ in range(MAX_TOOL_TURNS):
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOL_SCHEMAS,
            messages=history,
        )

        # Append assistant turn verbatim.
        history.append({"role": "assistant", "content": resp.content})

        # Collect tool_use blocks; if none, we're done.
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        for b in resp.content:
            if b.type == "text" and b.text:
                await cb.on_text(b.text)

        if resp.stop_reason != "tool_use" or not tool_uses:
            return history

        # Execute each tool call and prepare a user message of tool_result blocks.
        tool_results_content: list[dict] = []
        for tu in tool_uses:
            await cb.on_tool_call(tu.name, tu.input)
            try:
                result = dispatch(tu.name, tu.input or {}, sandbox)
            except Exception as e:
                result = {"error": f"{e.__class__.__name__}: {e}"}

            # Extract figures and emit them out-of-band; strip from the JSON we send back.
            figures_b64 = result.pop("_figures_b64", None) if isinstance(result, dict) else None
            if figures_b64:
                for b64 in figures_b64:
                    await cb.on_figure(base64.b64decode(b64))

            await cb.on_tool_result(tu.name, result)
            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str)[:60_000],  # hard cap to avoid runaway tokens
            })

        history.append({"role": "user", "content": tool_results_content})

    await cb.on_error(f"max tool turns ({MAX_TOOL_TURNS}) exceeded")
    return history


def make_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.  Copy .env.example to .env and fill it in.")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
