"""Prompt limits measure UTF-8 bytes with CRLF normalized to LF."""
from pathlib import Path


def content_bytes(path):
    return len(Path(path).read_bytes().replace(b"\r\n", b"\n"))
