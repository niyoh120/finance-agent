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
    assert config["sources"]["tickflow"]["api_key"] == "secret-token"
    # Sources not overridden by the TOML stay enabled by default.
    assert config["sources"]["tdx"]["enabled"] is True


def test_load_config_accepts_legacy_priority_key_for_backward_compat(tmp_path, monkeypatch):
    # Legacy `priority` keys in TOML are accepted (no error) but ignored: the
    # resolved SourceConfig has no priority field. This guards accidental
    # breakage of existing user configs during the priority removal migration.
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "openbb_finance.toml"
    config_file.write_text(
        """
[sources.tdx]
priority = 88
""",
        encoding="utf-8",
    )

    config = load_config(config_file)
    assert config["sources"]["tdx"]["priority"] == 88  # surfaced in raw dict
    assert not hasattr(get_source_config("tdx"), "priority")  # not on SourceConfig


def test_get_source_config_reads_openbb_finance_toml_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "openbb_finance.toml").write_text(
        """
[sources.akshare]
enabled = false
""",
        encoding="utf-8",
    )

    config = get_source_config("akshare")

    assert config.enabled is False


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
    assert config.base_url == "https://tdx.example.com"


def test_get_source_config_reads_finnhub_api_key_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FINNHUB_API_KEY", "finnhub-token")

    config = get_source_config("finnhub")

    assert config.enabled is True
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
