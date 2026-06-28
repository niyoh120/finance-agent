import os

from openbb_finance.config import apply_runtime_environment, get_source_config, load_config


def test_load_config_merges_toml_and_expands_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKFLOW_TOKEN", "secret-token")
    config_file = tmp_path / "openbb_finance.toml"
    config_file.write_text(
        """
[sources.tickflow]
enabled = false
priority = 88
api_key = "${TICKFLOW_TOKEN}"
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config["sources"]["tickflow"]["enabled"] is False
    assert config["sources"]["tickflow"]["priority"] == 88
    assert config["sources"]["tickflow"]["api_key"] == "secret-token"
    assert config["sources"]["tdx"]["priority"] == 110
    assert config["sources"]["baostock"]["priority"] == 90


def test_get_source_config_reads_openbb_finance_toml_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "openbb_finance.toml").write_text(
        """
[sources.akshare]
enabled = false
priority = 11
""",
        encoding="utf-8",
    )

    config = get_source_config("akshare")

    assert config.enabled is False
    assert config.priority == 11


def test_get_source_config_reads_tdx_base_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "openbb_finance.toml").write_text(
        """
[sources.tdx]
base_url = "https://tdx.example.com"
""",
        encoding="utf-8",
    )

    config = get_source_config("tdx")

    assert config.enabled is True
    assert config.priority == 110
    assert config.base_url == "https://tdx.example.com"


def test_get_source_config_reads_finnhub_api_key_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FINNHUB_API_KEY", "finnhub-token")

    config = get_source_config("finnhub")

    assert config.enabled is True
    assert config.priority == 102
    assert config.api_key == "finnhub-token"


def test_apply_runtime_environment_sets_database_url(tmp_path, monkeypatch):
    monkeypatch.delenv("FA_DATABASE_URL", raising=False)
    monkeypatch.setenv("TEST_DB_URL", "sqlite+aiosqlite:///openbb-finance-test.db")
    config_file = tmp_path / "openbb_finance.toml"
    config_file.write_text(
        """
[database]
url = "${TEST_DB_URL}"
""",
        encoding="utf-8",
    )

    apply_runtime_environment(load_config(config_file))

    assert os.environ["FA_DATABASE_URL"] == "sqlite+aiosqlite:///openbb-finance-test.db"
