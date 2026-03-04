from __future__ import annotations

from io import BytesIO

try:
    import discord
except (ImportError, ModuleNotFoundError) as exc:
    raise ImportError("`discord.py` not installed. Please install using `pip install discord.py`") from exc


class FullTextView(discord.ui.View):
    def __init__(
        self,
        *,
        full_text: str,
        requester_id: int | None,
        max_text_chars: int,
        timeout: float = 600.0,
    ):
        super().__init__(timeout=timeout)
        safe_max = max(1000, max_text_chars)
        self._full_text = full_text[:safe_max]
        self._requester_id = requester_id

    @discord.ui.button(label="查看全文", style=discord.ButtonStyle.secondary)
    async def show_full_text(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self._requester_id is not None and interaction.user.id != self._requester_id:
            await interaction.response.send_message("仅提问者可查看全文。", ephemeral=True)
            return

        if len(self._full_text) <= 1900:
            await interaction.response.send_message(self._full_text, ephemeral=True)
            return

        payload = BytesIO(self._full_text.encode("utf-8"))
        file = discord.File(payload, filename="trade-agent-reply.txt")
        await interaction.response.send_message("内容较长，已生成文本附件。", file=file, ephemeral=True)
