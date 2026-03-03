from __future__ import annotations

from dataclasses import dataclass

try:
    import discord
except (ImportError, ModuleNotFoundError) as exc:
    raise ImportError(
        "`discord.py` not installed. Please install using `pip install discord.py`"
    ) from exc


EMBED_DESCRIPTION_LIMIT = 4096


@dataclass
class FinalRender:
    content: str | None = None
    embed: discord.Embed | None = None


def normalize_markdown(text: str) -> str:
    normalized = sanitize_mentions(text.strip())
    if not normalized:
        return normalized

    return ensure_code_fence_closed(normalized)


def sanitize_mentions(text: str) -> str:
    return text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")


def ensure_code_fence_closed(text: str) -> str:
    if text.count("```") % 2 == 0:
        return text

    return f"{text}\n```"


def split_markdown_text(text: str, chunk_size: int) -> list[str]:
    if chunk_size <= 0 or len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.splitlines(keepends=True):
        if len(line) > chunk_size:
            if current:
                chunks.append(current)
                current = ""

            chunks.extend(_hard_split(line, chunk_size))
            continue

        if len(current) + len(line) <= chunk_size:
            current += line
            continue

        if current:
            chunks.append(current)
        current = line

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk]


def build_final_render(text: str, mode: str) -> FinalRender:
    final_text = normalize_markdown(text)
    normalized_mode = mode.strip().lower()

    if normalized_mode == "markdown":
        return FinalRender(content=final_text)

    if normalized_mode == "embed":
        embed = _build_embed(final_text)
        if embed is not None:
            return FinalRender(embed=embed)
        return FinalRender(content=final_text)

    embed = _build_embed(final_text)
    if embed is not None and len(final_text) <= 1600:
        return FinalRender(embed=embed)

    return FinalRender(content=final_text)


def _hard_split(text: str, chunk_size: int) -> list[str]:
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _build_embed(text: str) -> discord.Embed | None:
    if not text or len(text) > EMBED_DESCRIPTION_LIMIT:
        return None

    embed = discord.Embed(description=text)
    return embed
