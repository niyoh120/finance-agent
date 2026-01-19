import os

import chainlit as cl

from .pipeline import run_default
from .router import decide_route


async def _render_default(symbol: str) -> None:
    try:
        artifacts = await run_default(symbol)
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


@cl.on_chat_start
async def on_chat_start() -> None:
    # Use Chainlit user-provided env (configured via chainlit.toml user_env).
    user_env = cl.user_session.get("env") or {}
    if isinstance(user_env, dict):
        for k, v in user_env.items():
            if isinstance(k, str) and k and v is not None:
                os.environ.setdefault(k, str(v))

    res = await cl.AskUserMessage(
        content="请输入股票代码（例如 NASDAQ:AAPL）：",
        timeout=90,
        raise_on_timeout=False,
    ).send()

    symbol = None
    if res and isinstance(res, dict):
        symbol = (res.get("output") or "").strip()

    if not symbol:
        await cl.Message(content="未收到股票代码。你也可以直接提问并带上代码。").send()
        return

    cl.user_session.set("symbol", symbol)
    await _render_default(symbol)


@cl.on_message
async def on_message(msg: cl.Message) -> None:
    text = (msg.content or "").strip()

    if text.startswith("/update"):
        symbol = cl.user_session.get("symbol")
        if not symbol:
            await cl.Message(content="当前会话未设置标的，请先输入股票代码。").send()
            return
        await _render_default(symbol)
        return

    symbol = cl.user_session.get("symbol")
    if not symbol:
        await cl.Message(
            content="当前会话未设置标的，请先输入股票代码（例如 NASDAQ:AAPL）。"
        ).send()
        return

    decision = decide_route(user_text=text)
    await cl.Message(
        content=f"路由：{decision.reason}（{','.join([t.value for t in decision.timeframes])}）"
    ).send()

    # For now we always run default; later we will branch per decision.
    await _render_default(symbol)
