from agno.integrations.discord import DiscordClient

from .config import load_config
from .teams import build_chat_team

config = load_config()

chat_team = build_chat_team(
    config=config,
    stream=False,
    stream_events=False,
)

bot = DiscordClient(team=chat_team)

if __name__ == "__main__":
    bot.serve()
