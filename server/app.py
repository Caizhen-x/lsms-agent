"""Chainlit entrypoint.  Run with `make run` (or `chainlit run server/app.py -w`)."""
from __future__ import annotations

import json

import chainlit as cl

from .agent import AgentCallbacks, make_client, run_turn
from .config import GROUP_PASSWORD
from .sandbox import PythonSandbox


@cl.password_auth_callback
def auth(username: str, password: str) -> cl.User | None:
    if not GROUP_PASSWORD:
        # If no password configured, allow anything (dev mode).  Print a warning at startup.
        return cl.User(identifier=username or "dev", metadata={"role": "user"})
    if password == GROUP_PASSWORD:
        return cl.User(identifier=username or "researcher", metadata={"role": "user"})
    return None


@cl.on_chat_start
async def on_start() -> None:
    cl.user_session.set("client", make_client())
    cl.user_session.set("sandbox", PythonSandbox())
    cl.user_session.set("history", [])
    await cl.Message(
        content=(
            "Hi — I'm the LSMS agent. Ask me about Burkina Faso, Ethiopia, Malawi, Mali, "
            "Niger, Nigeria, Tanzania, or Uganda LSMS data. "
            "Try: *\"list all countries and rounds\"* or *\"find education variables in Tanzania 2010\"*."
        )
    ).send()


class ChainlitCallbacks(AgentCallbacks):
    def __init__(self) -> None:
        self.text_msg: cl.Message | None = None

    async def on_text(self, text: str) -> None:
        await cl.Message(content=text).send()

    async def on_tool_call(self, name: str, args: dict) -> None:
        # Render the tool call as a collapsible step so users can audit but it doesn't dominate the chat.
        async with cl.Step(name=f"🛠 {name}", type="tool") as step:
            step.input = json.dumps(args, indent=2, ensure_ascii=False, default=str)
        cl.user_session.set("last_step_name", name)

    async def on_tool_result(self, name: str, result: dict) -> None:
        async with cl.Step(name=f"↩ {name}", type="tool") as step:
            step.output = json.dumps(result, indent=2, ensure_ascii=False, default=str)[:5000]

    async def on_figure(self, png_bytes: bytes) -> None:
        await cl.Message(
            content="",
            elements=[cl.Image(name="plot.png", content=png_bytes, display="inline")],
        ).send()

    async def on_error(self, message: str) -> None:
        await cl.Message(content=f"⚠️ {message}").send()


@cl.on_message
async def on_message(msg: cl.Message) -> None:
    client = cl.user_session.get("client")
    sandbox = cl.user_session.get("sandbox")
    history = cl.user_session.get("history") or []

    cb = ChainlitCallbacks()
    new_history = await run_turn(client, history, msg.content, sandbox, cb)
    cl.user_session.set("history", new_history)
