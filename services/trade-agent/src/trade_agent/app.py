from __future__ import annotations

import logging
from typing import Any

from agno.os import AgentOS
from fastapi import FastAPI
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

agent_os = AgentOS(teams=[chat_team], workflows=[analysis_workflow])

app = FastAPI(title="Trade Agent API")
app.mount("/agent-os", agent_os.get_app())


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8089)
