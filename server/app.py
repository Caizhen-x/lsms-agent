"""Chainlit entrypoint.  Run with `make run` (or `chainlit run server/app.py -w`)."""
from __future__ import annotations

import json
import os

import chainlit as cl

# Defence-in-depth for CHAINLIT_AUTH_SECRET: Chainlit reads this env var during
# startup and on every JWT sign/verify.  If we leave it in os.environ, code
# running in the user-facing Python sandbox could read it and forge session
# cookies that survive password rotation.
#
# Fix: capture it once, scrub the env, and monkey-patch get_jwt_secret to read
# from our captured Python variable.  Chainlit imports get_jwt_secret into both
# chainlit.auth and chainlit.auth.jwt, so patch both bindings before Chainlit's
# startup ensure_jwt_secret() check runs.
import chainlit.auth as _cl_auth  # noqa: E402
import chainlit.auth.jwt as _cl_jwt  # noqa: E402

_AUTH_SECRET = os.environ.pop("CHAINLIT_AUTH_SECRET", None)
if _AUTH_SECRET:
    _cl_auth.get_jwt_secret = lambda: _AUTH_SECRET  # type: ignore[assignment]
    _cl_jwt.get_jwt_secret = lambda: _AUTH_SECRET  # type: ignore[assignment]

from server.agent import AgentCallbacks, make_client, run_turn  # noqa: E402
from server.config import GROUP_PASSWORD  # noqa: E402
from server.sandbox import PythonSandbox  # noqa: E402


# Fail closed: refuse to boot if no password is configured.  Previously had a
# dev-mode fallback that allowed anyone in when GROUP_PASSWORD was unset —
# catastrophic if the secret is ever fat-fingered in deployment.
if not GROUP_PASSWORD:
    raise RuntimeError(
        "GROUP_PASSWORD is not set.  Refusing to start: this would otherwise "
        "expose an open chat to anyone with the URL.  Set the secret in your "
        "deployment environment (HF Space settings -> Variables and secrets)."
    )


@cl.password_auth_callback
def auth(username: str, password: str) -> cl.User | None:
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
