import pytest
from openhop_apc_ups.mesh.text import clean_for_radio, split_for_meshcore


def test_clean_for_radio():
    dirty = "Hello\x00\x07World!   This  is   a   test.\n"
    cleaned = clean_for_radio(dirty)
    assert cleaned == "HelloWorld! This is a test."


def test_split_for_meshcore():
    short = "Short message"
    chunks = split_for_meshcore(short, max_chunk_bytes=50)
    assert chunks == ["Short message"]

    long_text = "Word1 " * 20
    chunks = split_for_meshcore(long_text, max_chunk_bytes=30)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= 30
