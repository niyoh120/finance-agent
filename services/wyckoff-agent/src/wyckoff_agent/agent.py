"""威科夫分析 Agent 构建

该模块提供 Agent 构建逻辑，Agent 通过 MCP toolset 获取数据，
并输出结构化的威科夫分析结果。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from .mcp_tools import create_mcp_toolset
from .schemas import WyckoffOverlay


@dataclass(frozen=True)
class AgentConfig:
    """Agent 配置"""

    openai_base_url: str
    openai_api_key: str
    openai_model: str


def load_agent_config() -> AgentConfig:
    """从环境变量加载 Agent 配置

    环境变量：
    - OPENAI_BASE_URL: OpenAI API base URL（默认官方 API）
    - OPENAI_API_KEY: OpenAI API key
    - OPENAI_MODEL: 模型名称（默认 gpt-4o）

    Returns:
        AgentConfig 实例
    """
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o"

    if not base_url:
        base_url = "https://api.openai.com/v1"

    return AgentConfig(
        openai_base_url=base_url, openai_api_key=api_key, openai_model=model
    )


def get_model():
    cfg = load_agent_config()

    if not cfg.openai_api_key:
        raise RuntimeError("缺少 OPENAI_API_KEY 环境变量")

    # 创建 OpenAI model
    # model = OpenAIChatModel(
    #     cfg.openai_model,
    #     provider=OpenAIProvider(
    #         base_url=cfg.openai_base_url, api_key=cfg.openai_api_key
    #     ),
    # )
    model = GoogleModel(
        cfg.openai_model,
        provider=GoogleProvider(
            base_url=cfg.openai_base_url, api_key=cfg.openai_api_key
        ),
    )
    return model


# System prompt for Wyckoff analysis
_WYCKOFF_SYSTEM_PROMPT = """\
你是交易史上最伟大的人物：理查德·D·威科夫（Richard D. Wyckoff）。

## 工作流程
1. 使用 fetch_stock_history 工具获取股票 K 线数据
   - 根据用户需求自主决定 symbol、timeframe、range 参数
   - 例如："4H 周期覆盖 1 年" → timeframe='240', range=2000
   - 例如："日线最近 200 根" → timeframe='D', range=200
   - 例如："1 分钟线日内" → timeframe='1', range=5000（注意 1 分钟线数据有 14 天限制）

2. 分析 K 线数据，识别威科夫结构
   - Phase A-E 阶段（不要强行凑齐，只输出能合理识别的部分）
   - 关键事件：SC/AR/ST/Spring/LPS/SOS/UTAD/JAC/SOW 等
   - 吸筹/派发区间：y_low/y_high 用 Phase B 收盘价密集区间，避免极端影线

3. 输出结构化分析结果
   - wyckoff_context: 价格周期背景（accumulation/distribution/markup/markdown/range）
   - phases: 阶段列表（每个阶段包含：名称、时间范围、置信度、理由）
   - events: 事件列表（每个事件包含：类型、时间、价格、理由）
   - zones: 区间列表（吸筹/派发区，包含时间范围和价格区间）
   - scenarios: 至少 3 种后续走势情景（概率之和约 1）
   - strategies: 至少 3 套交易策略（正股多/短期期权/LEAPS call 等）

## 要求
- 客观、严谨，不迎合用户
- 输出为中文，术语保持英文（SC/AR/ST 等）
- 每个判断必须有明确依据（价格结构、成交量、时间关系）
- 事件的 timestamp 必须对应 K 线数据中的实际时间点
- zones 的 x0/x1 用关键事件区间（例如从 SC 到最后一次 SOS/JAC）
"""


def build_wyckoff_agent() -> Agent[None, WyckoffOverlay]:
    """构建威科夫分析 Agent

    该 Agent 具备以下能力：
    1. 通过 MCP toolset 调用 fetch_stock_history 获取 K 线数据
    2. 分析威科夫结构并输出 WyckoffOverlay

    Returns:
        配置好的 Agent 实例，输出类型为 WyckoffOverlay
    """

    # 创建 MCP toolset
    mcp_toolset = create_mcp_toolset()

    return Agent(
        model=get_model(),
        system_prompt=_WYCKOFF_SYSTEM_PROMPT,
        output_type=WyckoffOverlay,  # 结构化输出
        toolsets=[mcp_toolset],  # MCP 作为工具
        retries=2,  # 允许重试（如果 LLM 输出格式错误）
    )


_CHAT_PROMPT = """
角色设定：

你现在是交易史上最伟大的人物理查德·D·威科夫（Richard D. Wyckoff）。你的任务如下

- 预测几种可能的后续走势，要给出每种走势的大致概率，从高到低排序。

- 给出几种详细的交易策略，比如做多正股、短期期权、leaps call、做空正股等等，要包含止盈和止损点和必要的风险提示。

请检查并确认分析结果是完全符合威科夫技术分析方法的，然后再发出给我。

后续的交流要秉持客观严谨的态度，不要为了迎合我的想法修改自己的判断。如果你需要更多数据来辅助分析，请使用工具获取相关数据。
"""


def build_chat_agent() -> Agent[None, str]:
    # 创建 MCP toolset
    mcp_toolset = create_mcp_toolset()

    return Agent(
        model=get_model(),
        system_prompt=_CHAT_PROMPT,
        toolsets=[mcp_toolset],  # MCP 作为工具
    )
