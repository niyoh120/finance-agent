from shared.logging import configure_logging

from .config import load_config
from .discord_adapter import TradeDiscordBot
from .teams import build_chat_team

configure_logging(service="trade-agent-discord-bot")

config = load_config()

chat_team = build_chat_team(
    config=config,
    stream=True,
    stream_events=config.discord_bot.stream_events,
    stream_member_events=config.discord_bot.stream_member_events,
    num_history_runs=config.discord_bot.num_history_runs,
)

bot = TradeDiscordBot(team=chat_team, config=config.discord_bot)

if __name__ == "__main__":
    bot.serve()
