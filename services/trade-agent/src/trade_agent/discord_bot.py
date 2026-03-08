import openlit
from agno.db.sqlite import SqliteDb
from langfuse import get_client
from shared.logging import configure_logging

from .config import load_config
from .discord_adapter import TradeDiscordBot
from .teams import build_chat_team

configure_logging(service="trade-agent-discord-bot")

config = load_config()

langfuse = get_client()


# Verify connection
assert langfuse.auth_check(), "Langfuse authentication failed. Please check your credentials and host."

openlit.init(tracer=langfuse._otel_tracer, disable_batch=True)


def build_discord_team():
    compression_manager = None
    if config.discord_bot.compress_token_limit is not None:
        try:
            from agno.compression.manager import CompressionManager
        except (ImportError, ModuleNotFoundError) as exc:
            raise ImportError(
                "agno compression manager unavailable, cannot use discord_bot.compress_token_limit"
            ) from exc

        compression_manager = CompressionManager(
            model=config.get_model_for_agent("trade_analyst"),
            compress_tool_results=config.discord_bot.compress_tool_results,
            compress_token_limit=config.discord_bot.compress_token_limit,
        )

    return build_chat_team(
        config=config,
        stream=True,
        stream_events=config.discord_bot.stream_events,
        stream_member_events=config.discord_bot.stream_member_events,
        num_history_runs=config.discord_bot.num_history_runs,
        db=SqliteDb(db_file=config.storage.sqlite_db_path),
        add_history_to_context=config.discord_bot.add_history_to_context,
        enable_session_summaries=config.discord_bot.enable_session_summaries,
        add_session_summary_to_context=config.discord_bot.add_session_summary_to_context,
        compress_tool_results=config.discord_bot.compress_tool_results,
        compression_manager=compression_manager,
    )


bot = TradeDiscordBot(team_factory=build_discord_team, config=config.discord_bot)

if __name__ == "__main__":
    bot.serve()
