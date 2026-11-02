"""Text cleaning and chunking utilities for MeshCore radio packets."""

from __future__ import annotations

import re

_DISALLOWED_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTIPLE_SPACES = re.compile(r"[ \t]+")


def clean_for_radio(text: str) -> str:
    """Normalize text into clean plain text suitable for LoRa radio transmission."""
    text = _DISALLOWED_CHARS.sub("", text)
    text = _MULTIPLE_SPACES.sub(" ", text)
    return text.strip()


def split_for_meshcore(text: str, max_chunk_bytes: int = 120) -> list[str]:
    """Split text into chunks that fit within MeshCore radio payload limits."""
    text = clean_for_radio(text)
    if not text:
        return []

    encoded = text.encode("utf-8")
    if len(encoded) <= max_chunk_bytes:
        return [text]

    chunks: list[str] = []
    words = text.split(" ")
    current_chunk: list[str] = []
    current_len = 0

    for word in words:
        word_len = len(word.encode("utf-8"))
        # +1 for space if current_chunk is not empty
        space_len = 1 if current_chunk else 0

        if current_len + space_len + word_len <= max_chunk_bytes:
            current_chunk.append(word)
            current_len += space_len + word_len
        else:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_len = 0

            # If a single word is larger than max_chunk_bytes, slice it
            while len(word.encode("utf-8")) > max_chunk_bytes:
                # Find byte slice
                part = word.encode("utf-8")[:max_chunk_bytes].decode("utf-8", errors="ignore")
                chunks.append(part)
                word = word[len(part):]

            if word:
                current_chunk.append(word)
                current_len = len(word.encode("utf-8"))

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks
