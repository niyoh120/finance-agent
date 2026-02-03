from agno.db.sqlite import SqliteDb
from agno.team.team import Team

from ..agents import (
    build_fundamental_analyst,
    build_options_flow_analyst,
    build_sentiment_analyst,
    build_technical_analyst,
    build_wyckoff_analyst,
)
from ..config import AppConfig


def build_chat_team(config: AppConfig) -> Team:
    db = SqliteDb(db_file=config.storage.sqlite_db_path)

    team = Team(
        name="Trade Analyst Team",
        model=config.get_model_for_agent("trade_analyst"),
        db=db,
        members=[
            build_technical_analyst(config),
            build_options_flow_analyst(config),
            build_sentiment_analyst(config),
            build_fundamental_analyst(config),
            build_wyckoff_analyst(config),
        ],
        instructions=[
            "根据用户问题选择相关的分析师进行分析，根据分析结果使用中文回答。",
        ],
        share_member_interactions=True,
        markdown=True,
        stream=True,
        stream_events=True,
        add_history_to_context=True,
        num_history_runs=15,
        **config.get_params_for_agent("trade_analyst"),
    )

    return team
