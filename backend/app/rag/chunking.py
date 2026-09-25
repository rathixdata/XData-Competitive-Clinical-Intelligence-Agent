"""Structure-aware chunking. Sections from adapters are chunked independently so every chunk maps to
one source field (claim-level provenance, FR-AI-003); long sections are packed by sentence with overlap."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(\"'])|\n+|\s+(?=\d+\.\s)|\s+(?=[-*•]\s)")


def approx_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.33))


@dataclass
class Chunk:
    text: str
    char_start: int
    char_end: int
    token_count: int


def chunk_text(text: str, max_tokens: int = 350, overlap_tokens: int = 60) -> list[Chunk]:
    text = (text or "").strip()
    if not text:
        return []
    if approx_tokens(text) <= max_tokens:
        return [Chunk(text, 0, len(text), approx_tokens(text))]
    # sentence spans with offsets
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _SENT.finditer(text):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    # split very long sentences by words
    fine: list[tuple[int, int]] = []
    for s, e in spans:
        seg = text[s:e]
        if approx_tokens(seg) <= max_tokens:
            fine.append((s, e))
            continue
        words = list(re.finditer(r"\S+", seg))
        step = int(max_tokens / 1.33)
        for i in range(0, len(words), step):
            w = words[i : i + step]
            fine.append((s + w[0].start(), s + w[-1].end()))
    chunks: list[Chunk] = []
    i = 0
    while i < len(fine):
        start = fine[i][0]
        j, toks = i, 0
        while j < len(fine) and (toks + approx_tokens(text[fine[j][0]:fine[j][1]]) <= max_tokens or j == i):
            toks += approx_tokens(text[fine[j][0]:fine[j][1]])
            j += 1
        end = fine[j - 1][1]
        chunks.append(Chunk(text[start:end], start, end, toks))
        if j >= len(fine):
            break
        # overlap: step back sentences worth ~overlap_tokens
        back, k = 0, j
        while k - 1 > i and back < overlap_tokens:
            k -= 1
            back += approx_tokens(text[fine[k][0]:fine[k][1]])
        i = k if k > i else j
    return chunks
