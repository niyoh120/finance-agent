from typing import Any

from agno.db.sqlite import SqliteDb
from agno.team.team import Team

from ..agents import (
    build_cn_fundamental_analyst,
    build_macro_analyst,
    build_options_flow_analyst,
    build_sentiment_analyst,
    build_technical_analyst,
    build_us_fundamental_analyst,
    build_wyckoff_analyst,
)
from ..config import AppConfig


def build_chat_team(
    config: AppConfig,
    stream: bool = True,
    stream_events: bool = True,
    stream_member_events: bool = True,
    num_history_runs: int = 15,
    db: SqliteDb | None = None,
    add_history_to_context: bool = True,
    enable_session_summaries: bool = False,
    add_session_summary_to_context: bool = False,
    compress_tool_results: bool = False,
    compression_manager: Any | None = None,
) -> Team:
    team = Team(
        name="Trade Analyst Team",
        model=config.get_model_for_agent("trade_analyst"),
        db=db,
        members=[
            build_technical_analyst(config),
            build_options_flow_analyst(config),
            build_sentiment_analyst(config),
            build_cn_fundamental_analyst(config),
            build_us_fundamental_analyst(config),
            build_macro_analyst(config),
            build_wyckoff_analyst(config),
        ],
        instructions=[
            "根据用户问题选择相关的分析师进行分析，根据分析结果使用中文回答。",
            "对于技术面分析：需要重点参考威科夫分析师的结论、技术分析师的结论作为补充；"
            "对于基本面分析：如果涉及A股或港股（6位数字代码或.HK后缀），选择CN Fundamental Analyst；"
            "如果涉及美股（字母代码），选择US Fundamental Analyst。",
        ],
        share_member_interactions=True,
        markdown=True,
        add_history_to_context=add_history_to_context,
        enable_session_summaries=enable_session_summaries,
        add_session_summary_to_context=add_session_summary_to_context,
        stream=stream,
        stream_events=stream_events,
        stream_member_events=stream_member_events,
        num_history_runs=num_history_runs,
        compress_tool_results=compress_tool_results,
        compression_manager=compression_manager,
        **config.get_params_for_agent("trade_analyst"),
    )

    return team
