import logging
from typing import Any

from agno.os import AgentOS
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from shared.logging import configure_logging

from .agents import (
    build_fundamental_analyst,
    build_options_flow_analyst,
    build_sentiment_analyst,
    build_technical_analyst,
    build_wyckoff_analyst,
)
from .analysis_engine import AnalysisEngine, build_analysis_workflow
from .chat_team import build_chat_team
from .config import load_config
from .models import TradingDecision

configure_logging(service="trade-agent")
logger = logging.getLogger(__name__)


def build_agents(config):
    fundamental_analyst = build_fundamental_analyst(config)
    options_flow_analyst = build_options_flow_analyst(config)
    sentiment_analyst = build_sentiment_analyst(config)
    technical_analyst = build_technical_analyst(config)
    wyckoff_analyst = build_wyckoff_analyst(config)

    return [
        fundamental_analyst,
        options_flow_analyst,
        sentiment_analyst,
        technical_analyst,
        wyckoff_analyst,
    ]


config = load_config()
analysis_engine = AnalysisEngine(config)
analysis_workflow = build_analysis_workflow(config)
chat_team = build_chat_team(config)


app = FastAPI(title="Trade Agent API")
agent_os = AgentOS(
    base_app=app,
    teams=[chat_team],
    workflows=[analysis_workflow],
    agents=build_agents(config),
)


class AnalysisRequest(BaseModel):
    ticker: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    content: Any


@app.post("/analysis/run", response_model=TradingDecision)
def run_analysis(request: AnalysisRequest) -> TradingDecision:
    return analysis_engine.run(request.ticker)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    response = chat_team.run(
        request.message,
        session_id=request.session_id,
        stream=False,
    )
    return ChatResponse(content=response.content)


app = agent_os.get_app()

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


if __name__ == "__main__":
    agent_os.serve(app=app, host="0.0.0.0", port=8089)
