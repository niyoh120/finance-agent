from langfuse import get_client
import openlit

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
    return build_chat_team(
        config=config,
        stream=True,
        stream_events=config.discord_bot.stream_events,
        stream_member_events=config.discord_bot.stream_member_events,
        num_history_runs=config.discord_bot.num_history_runs,
        db=None,
        add_history_to_context=False,
    )


bot = TradeDiscordBot(team_factory=build_discord_team, config=config.discord_bot)

if __name__ == "__main__":
    bot.serve()
