"""Versioned prompt registry. Prompts live in ``*.md`` files with a front-matter header:

    ---
    id: impact_narrative
    version: 1.2.0
    ---
    <system prompt text>

The content hash is recorded on every GenerationRecord so historical outputs remain auditable after
prompt changes (FR-AI-007). Promotion of a changed prompt goes through the evaluation gate in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.crypto import sha256_hex

_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    text: str

    @property
    def hash(self) -> str:
        return sha256_hex(self.text)


@lru_cache
def load_prompt(prompt_id: str) -> Prompt:
    raw = (_DIR / f"{prompt_id}.md").read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = raw
    if raw.startswith("---"):
        _, header, body = raw.split("---", 2)
        for line in header.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return Prompt(id=meta.get("id", prompt_id), version=meta.get("version", "0.0.0"), text=body.strip())


def all_prompts() -> list[Prompt]:
    return [load_prompt(p.stem) for p in sorted(_DIR.glob("*.md"))]
