"""Configuration for finance data sources."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceConfig:
    name: str
    enabled: bool
    api_key: str | None = None
    base_url: str | None = None


# Source ordering is controlled by the `ordered_by_names([...])` call in each
# model (the list order is the fallback order); no numeric priority is needed.
# This map only exists so that sources enabled by default and the API key
# placeholders are declared in one place.
DEFAULT_SOURCES: tuple[str, ...] = (
    "tdx",
    "tickflow",
    "finnhub",
    "futunn",
    "convexvalue",
    "sina",
    "eastmoney",
    "baostock",
    "akshare",
    "openbb",
    "schwab",
)

DEFAULT_CONFIG: dict[str, Any] = {"sources": {name: {"enabled": True} for name in DEFAULT_SOURCES}}
DEFAULT_CONFIG["sources"]["finnhub"]["api_key"] = "${FINNHUB_API_KEY}"
DEFAULT_CONFIG["sources"]["convexvalue"]["api_key"] = "${CV_API_KEY}"
# schwab-api service endpoint: the placeholder collapses to "" when the env var
# is unset, so SchwabSource.enabled is False and routing falls back to
# tdx/tickflow at zero cost. api_key is optional (service-side X-API-Key gate).
DEFAULT_CONFIG["sources"]["schwab"]["base_url"] = "${SCHWAB_API_BASE_URL}"
DEFAULT_CONFIG["sources"]["schwab"]["api_key"] = "${SCHWAB_API_KEY}"
# tdx-api service endpoint (services/tdx-api, default http://127.0.0.1:8011):
# same gating scheme as schwab — unset TDX_API_BASE_URL expands to "" and the
# TDX source is disabled at zero cost. TDX_API_KEY must match the service-side
# FA_TDX_API_KEY when that gate is enabled; it travels as the X-API-Key header.
DEFAULT_CONFIG["sources"]["tdx"]["base_url"] = "${TDX_API_BASE_URL}"
DEFAULT_CONFIG["sources"]["tdx"]["api_key"] = "${TDX_API_KEY}"

CONFIG_FILENAMES = ("openbb_finance.toml", ".openbb_finance.toml")
ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def _candidate_paths() -> list[Path]:
    cwd = Path.cwd()
    paths = [cwd / filename for filename in CONFIG_FILENAMES]
    paths.append(Path.home() / ".config" / "openbb_finance" / "config.toml")
    return paths


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config = DEFAULT_CONFIG
    config_path = Path(path) if path is not None else next((p for p in _candidate_paths() if p.exists()), None)
    if config_path is not None and config_path.exists():
        with config_path.open("rb") as file:
            config = _deep_merge(config, tomllib.load(file))
    return _expand_env(config)


def apply_runtime_environment(config: dict[str, Any] | None = None) -> None:
    """Apply sensitive values needed by finance-shared from TOML config."""

    data = config or load_config()
    database = data.get("database", {})
    if isinstance(database, dict):
        url = database.get("url")
        if isinstance(url, str) and url:
            os.environ.setdefault("FA_DATABASE_URL", url)


def get_source_config(name: str) -> SourceConfig:
    config = load_config()
    source = config.get("sources", {}).get(name, {})
    enabled = bool(source.get("enabled", True))
    api_key = source.get("api_key")
    base_url = source.get("base_url")
    return SourceConfig(name=name, enabled=enabled, api_key=api_key, base_url=base_url)
