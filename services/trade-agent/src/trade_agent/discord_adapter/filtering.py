from __future__ import annotations

try:
    import discord
except (ImportError, ModuleNotFoundError) as exc:
    raise ImportError("`discord.py` not installed. Please install using `pip install discord.py`") from exc


ALLOWED_MESSAGE_TYPES: set[discord.MessageType] = {
    discord.MessageType.default,
    discord.MessageType.reply,
}


def should_process_message(message: discord.Message, bot_user_id: int | None) -> bool:
    if not isinstance(message.channel, discord.Thread):
        return False

    if bot_user_id is not None and message.author.id == bot_user_id:
        return False

    if message.author.bot:
        return False

    if message.webhook_id is not None:
        return False

    if message.type not in ALLOWED_MESSAGE_TYPES:
        return False

    has_text = bool(message.content and message.content.strip())
    has_attachments = bool(message.attachments)
    return has_text or has_attachments
