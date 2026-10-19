"""Document parsing and section-aware chunking.

Markdown is split on headings so each chunk carries the section it came from (used in citations as
`source_section`). Long sections are split on paragraph boundaries with a small overlap. YAML-ish
front matter supplies title / type / version metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.M)


@dataclass
class Chunk:
    index: int
    section: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Minimal `key: value` front-matter parser (no nested YAML needed for our docs)."""
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    current_key = None
    for line in match.group(1).splitlines():
        if re.match(r"^[A-Za-z_][\w-]*\s*:", line):
            key, _, value = line.partition(":")
            current_key = key.strip()
            meta[current_key] = value.strip().strip('"').strip("'").lstrip(">").strip()
        elif current_key and line.startswith((" ", "\t")):
            meta[current_key] = (meta[current_key] + " " + line.strip()).strip()
    return meta, text[match.end():]


def _split_long(text: str, target: int, overlap: int) -> list[str]:
    if len(text) <= target:
        return [text]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > target:
            pieces.append(current)
            tail = current[-overlap:] if overlap else ""
            current = (tail + "\n\n" + para).strip() if tail else para
        else:
            current = f"{current}\n\n{para}".strip()
    if current:
        pieces.append(current)
    # A single paragraph longer than target: hard-split on sentences.
    out: list[str] = []
    for piece in pieces:
        if len(piece) <= target * 1.5:
            out.append(piece)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", piece)
        buf = ""
        for s in sentences:
            if buf and len(buf) + len(s) > target:
                out.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            out.append(buf)
    return out


def chunk_markdown(text: str, *, title: str, target_chars: int = 1200, overlap_chars: int = 150) -> list[Chunk]:
    headings = list(_HEADING.finditer(text))
    sections: list[tuple[str, str]] = []
    if not headings:
        sections.append((title, text))
    else:
        preamble = text[: headings[0].start()].strip()
        if preamble:
            sections.append((title, preamble))
        for i, h in enumerate(headings):
            body = text[h.end(): headings[i + 1].start() if i + 1 < len(headings) else len(text)].strip()
            level, name = len(h.group(1)), h.group(2).strip()
            if level == 1 and not body:
                continue
            sections.append((name, body))
    chunks: list[Chunk] = []
    for section, body in sections:
        if not body.strip():
            continue
        for piece in _split_long(body, target_chars, overlap_chars):
            # Prefix the section name so both BM25 and embeddings see the heading context.
            chunks.append(Chunk(len(chunks), section, f"{section}\n{piece}".strip()))
    return chunks


def chunk_plain(text: str, *, title: str, target_chars: int = 1200, overlap_chars: int = 150) -> list[Chunk]:
    return [Chunk(i, title, piece) for i, piece in enumerate(_split_long(text.strip(), target_chars, overlap_chars)) if piece]
