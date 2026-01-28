import os
import re
from pathlib import Path
from typing import Any

import yaml
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.models.openai.like import OpenAILike
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    provider: str
    model_id: str = Field(alias="model_id")
    base_url: str | None = None
    api_key_env: str | None = None


class MCPConfig(BaseModel):
    url: str


class StockApiConfig(BaseModel):
    url: str | None = None


class StorageConfig(BaseModel):
    sqlite_db_path: str = "agno.db"


class RiskConfig(BaseModel):
    max_portfolio_volatility: float = 0.15
    var_confidence: float = 0.95
    volatility_lookback_days: int = 60
    max_position_limit: float = 0.2


class AnalysisConfig(BaseModel):
    timeframe: str = "D"
    history_range: int = 200
    signal_weights: dict[str, float] = Field(default_factory=dict)


class AppConfig(BaseModel):
    models: dict[str, ModelConfig]
    mcp_server: MCPConfig
    stock_api: StockApiConfig = StockApiConfig()
    storage: StorageConfig = StorageConfig()
    risk_parameters: RiskConfig = RiskConfig()
    analysis: AnalysisConfig = AnalysisConfig()

    def get_model_for_agent(self, agent_name: str) -> Any:
        """Get the model for a specific agent, fallback to 'default' if not found."""
        model_config = self.models.get(agent_name)
        if not model_config:
            model_config = self.models.get("default")

        if not model_config:
            raise ValueError(
                f"No model configuration found for agent '{agent_name}' and no 'default' model defined."
            )

        return build_model(model_config)


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        name = match.group(1)
        return os.getenv(name, "")

    return _ENV_PATTERN.sub(replacer, value)


def _expand_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: _expand_obj(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_expand_obj(value) for value in obj]
    if isinstance(obj, str):
        return _expand_env(obj)
    return obj


def load_config(path: str | None = None) -> AppConfig:
    config_path = path or os.getenv("FA_TRADE_AGENT_CONFIG")
    if not config_path:
        config_path = str(Path(__file__).resolve().parents[2] / "config.yaml")

    with open(config_path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    expanded = _expand_obj(raw)
    config = AppConfig.model_validate(expanded)

    return config


def build_model(model_config: ModelConfig):
    provider = model_config.provider.strip().lower()

    if provider in {"openai", "openai_chat"}:
        return OpenAIChat(id=model_config.model_id, base_url=model_config.base_url)

    if provider in {
        "openai-like",
        "openai_like",
        "openai-compatible",
        "openai_compatible",
        "deepseek",
    }:
        api_key = os.getenv(model_config.api_key_env or "OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        return OpenAILike(
            id=model_config.model_id,
            base_url=model_config.base_url or base_url,
            api_key=api_key,
        )

    if provider in {"gemini", "google"}:
        return Gemini(id=model_config.model_id)

    if provider in {"anthropic", "claude"}:
        return Claude(id=model_config.model_id)

    raise ValueError(f"Unsupported model provider: {model_config.provider}")
