from __future__ import annotations

import logging
from typing import Any

from agno.os import AgentOS
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from shared.logging import configure_logging

from .analysis_engine import AnalysisEngine, build_analysis_workflow
from .chat_team import build_chat_team
from .config import load_config
from .models import TradingDecision

configure_logging(service="trade-agent")
logger = logging.getLogger(__name__)

config = load_config()
analysis_engine = AnalysisEngine(config)
analysis_workflow = build_analysis_workflow(config)
chat_team = build_chat_team(config)

app = FastAPI(title="Trade Agent API")
agent_os = AgentOS(base_app=app, teams=[chat_team], workflows=[analysis_workflow])


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    agent_os.serve(app=app, host="0.0.0.0", port=8089)
