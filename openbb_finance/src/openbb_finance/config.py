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
    priority: int
    api_key: str | None = None


DEFAULT_PRIORITIES = {
    "futunn": 100,
    "sina": 98,
    "eastmoney": 95,
    "baostock": 90,
    "tickflow": 80,
    "akshare": 70,
    "yahoo": 60,
    "openbb": 50,
}


DEFAULT_CONFIG: dict[str, Any] = {
    "sources": {
        name: {"enabled": True, "priority": priority}
        for name, priority in DEFAULT_PRIORITIES.items()
    }
}

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
    priority = int(source.get("priority", DEFAULT_PRIORITIES.get(name, 50)))
    api_key = source.get("api_key")
    return SourceConfig(name=name, enabled=enabled, priority=priority, api_key=api_key)
