import logging
from email import message

import chainlit as cl
from pydantic_ai import (
    ModelMessage,
    ModelResponse,
    TextPart,
)

from .agent import build_chat_agent, build_wyckoff_agent
from .logging_utils import configure_logging
from .pipeline import run_default

configure_logging()

logger = logging.getLogger(__name__)


async def save_chat_history(messages: list[ModelMessage]):
    cl.user_session.set("__chat_history", messages)


async def get_chat_history() -> list[ModelMessage] | None:
    return cl.user_session.get("__chat_history", [])


async def _render_analysis(agent, symbol_message: str) -> None:
    """运行分析并渲染结果"""
    try:
        artifacts, messages = await run_default(agent, symbol_message)
    except Exception as exc:
        await cl.Message(content=f"运行失败：{exc}").send()
        return

    elements: list[cl.Element] = [
        cl.Plotly(name="wyckoff", figure=artifacts.figure, display="inline"),
    ]

    if artifacts.png_path:
        elements.append(
            cl.File(name="wyckoff.png", path=artifacts.png_path, display="inline")
        )

    if artifacts.analysis_json_path:
        elements.append(
            cl.File(
                name="analysis.json",
                path=artifacts.analysis_json_path,
                display="inline",
            )
        )

    if artifacts.figure_json_path:
        elements.append(
            cl.File(
                name="figure.json", path=artifacts.figure_json_path, display="inline"
            )
        )

    await cl.Message(content=artifacts.analysis.summary, elements=elements).send()
    await cl.Message(content=artifacts.analysis.details).send()

    await save_chat_history(messages)


@cl.data_layer
def get_data_layer():
    return None


@cl.on_chat_start
async def on_chat_start() -> None:
    res = await cl.AskUserMessage(
        content="请输入股票代码",
        timeout=90,
        raise_on_timeout=False,
    ).send()

    symbol_msg = None
    if res and isinstance(res, dict):
        symbol_msg = (res.get("output") or "").strip()

    if not symbol_msg:
        await cl.Message(content="未收到股票代码。你也可以直接提问并带上代码。").send()
        return

    agent = build_wyckoff_agent()

    await _render_analysis(agent, symbol_msg)


def get_model_message(output) -> str | None:
    msg = ModelResponse(parts=[TextPart(output)])
    first_part = msg.parts[0]
    if isinstance(first_part, TextPart):
        return first_part.content
    return None


@cl.on_message
async def on_message(msg: cl.Message) -> None:
    agent = cl.user_session.get("agent")
    if agent is None:
        agent = build_chat_agent()
        cl.user_session.set("agent", agent)

    chat_history = await get_chat_history()

    reply_msg = None
    async with agent.run_stream(
        user_prompt=msg.content, message_history=chat_history
    ) as result:
        async for output in result.stream_output():
            text = get_model_message(output)
            if not text:
                continue
            if reply_msg is None:
                reply_msg = await cl.Message(content="").send()
            await reply_msg.stream_token(text)
        await save_chat_history(result.all_messages())
        if reply_msg:
            await reply_msg.send()


@cl.on_chat_resume
async def on_chat_resume(thread):
    pass
