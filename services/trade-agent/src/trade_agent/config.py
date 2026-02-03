import os
from pathlib import Path
from typing import Annotated, Any, Literal

from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat, OpenAILike, OpenAIResponses, OpenResponses
from pydantic import BeforeValidator, Field, HttpUrl, TypeAdapter
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    YamlConfigSettingsSource,
)

http_url_adapter = TypeAdapter(HttpUrl)
StrHttpUrl = Annotated[
    str, BeforeValidator(lambda value: str(http_url_adapter.validate_python(value)))
]


class ModelConfig(BaseSettings):
    provider: str
    model_id: str
    base_url: StrHttpUrl | None = None
    api_key_env: str | None = None

    # openai
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None

    # gemini
    thinking_level: Literal["low", "high"] | None = None


class AgentConfig(BaseSettings):
    model: ModelConfig
    params: dict[str, Any]


class MCPConfig(BaseSettings):
    url: StrHttpUrl
    api_key: str | None = None


class StockApiConfig(BaseSettings):
    url: StrHttpUrl


class StorageConfig(BaseSettings):
    sqlite_db_path: str


class RiskConfig(BaseSettings):
    max_portfolio_volatility: float = 0.15
    var_confidence: float = 0.95
    volatility_lookback_days: int = 60
    max_position_limit: float = 0.2


class AnalysisConfig(BaseSettings):
    signal_weights: dict[str, float] = Field(default_factory=dict)


class AppConfig(BaseSettings):
    agents: dict[str, AgentConfig]
    mcp_server: MCPConfig
    stock_api: StockApiConfig
    storage: StorageConfig
    risk_parameters: RiskConfig
    analysis: AnalysisConfig

    def _get_agent_config(self, agent_name: str) -> AgentConfig:
        agent_config = self.agents.get(agent_name)
        if not agent_config:
            agent_config = self.agents.get("default")

        if not agent_config:
            raise ValueError(
                f"No agent configuration found for agent '{agent_name}' and no 'default' defined."
            )
        return agent_config

    def get_model_for_agent(self, agent_name: str) -> Any:
        """Get the model for a specific agent, fallback to 'default' if not found."""
        return build_model(self._get_agent_config(agent_name).model)

    def get_params_for_agent(self, agent_name: str) -> dict[str, Any]:
        """Get the parameters for a specific agent, fallback to 'default' if not found."""
        return self._get_agent_config(agent_name).params or {}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        default_config_path = str(Path(__file__).resolve().parents[2] / "config.yaml")
        config_path = Path(os.getenv("FA_TRADE_AGENT_CONFIG", default_config_path))

        return (YamlConfigSettingsSource(settings_cls, yaml_file=config_path),)


def build_model(model_config: ModelConfig):
    provider = model_config.provider.strip().lower()

    if provider in {
        "openai",
    }:
        base_url = os.getenv("OPENAI_BASE_URL")
        return OpenAIChat(
            id=model_config.model_id,
            base_url=model_config.base_url or base_url,
            reasoning_effort=model_config.reasoning_effort,
        )

    if provider in {
        "openai-like",
    }:
        api_key = os.getenv(model_config.api_key_env or "OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        return OpenAILike(
            id=model_config.model_id,
            base_url=model_config.base_url or base_url,
            api_key=api_key,
            reasoning_effort=model_config.reasoning_effort,
        )

    if provider in {"openai-responses"}:
        base_url = os.getenv("OPENAI_BASE_URL")
        return OpenAIResponses(
            id=model_config.model_id,
            base_url=model_config.base_url or base_url,
        )

    if provider in {"open-responses"}:
        api_key = os.getenv(model_config.api_key_env or "OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        return OpenResponses(
            id=model_config.model_id,
            base_url=model_config.base_url or base_url,
            api_key=api_key,
        )

    if provider in {"gemini", "google"}:
        return Gemini(
            id=model_config.model_id, thinking_level=model_config.thinking_level
        )

    if provider in {"anthropic", "claude"}:
        return Claude(id=model_config.model_id)

    raise ValueError(f"Unsupported model provider: {model_config.provider}")


def load_config() -> AppConfig:
    return AppConfig()  # type: ignore
