import structlog
from agno.os import AgentOS
from agno.agent import Agent
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.logging import configure_logging

from .agents import (
    build_cn_fundamental_analyst,
    build_macro_analyst,
    build_options_flow_analyst,
    build_risk_manager,
    build_sentiment_analyst,
    build_technical_analyst,
    build_us_fundamental_analyst,
    build_wyckoff_agent,
    build_wyckoff_analyst,
)
from .config import load_config
from .teams import build_chat_team
from .workflows import (
    build_analysis_workflow,
)

configure_logging(service="trade-agent")
logger = structlog.get_logger(__name__)


def build_agents(config) -> list[Agent]:
    cn_fundamental_analyst = build_cn_fundamental_analyst(config)
    us_fundamental_analyst = build_us_fundamental_analyst(config)
    macro_analyst = build_macro_analyst(config)
    options_flow_analyst = build_options_flow_analyst(config)
    sentiment_analyst = build_sentiment_analyst(config)
    technical_analyst = build_technical_analyst(config)
    wyckoff_analyst = build_wyckoff_analyst(config)
    risk_manager = build_risk_manager(config)
    wyckoff_agent = build_wyckoff_agent(config)

    return [
        cn_fundamental_analyst,
        us_fundamental_analyst,
        macro_analyst,
        options_flow_analyst,
        sentiment_analyst,
        technical_analyst,
        risk_manager,
        wyckoff_analyst,
        wyckoff_agent,
    ]


config = load_config()
logger.info("Load config succ.", config=config)
analysis_workflow = build_analysis_workflow(config)
chat_team = build_chat_team(config)


app = FastAPI(title="Trade Agent API")
agent_os = AgentOS(
    base_app=app,
    teams=[chat_team],
    workflows=[analysis_workflow],
    agents=build_agents(config),
    tracing=True,
)


app = agent_os.get_app()

app.add_middleware(
    CORSMiddleware,  # type: ignore
    allow_origin_regex=r"http(s?)://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    agent_os.serve(app=app, host="0.0.0.0", port=8089)
