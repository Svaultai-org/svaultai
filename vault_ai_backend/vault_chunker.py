

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

                                                                          
try:
    from vault_config import brain as _brain_cfg
    _b = _brain_cfg()
    DEFAULT_TARGET_CHARS  = _b.chunk_target_chars
    DEFAULT_OVERLAP_CHARS = _b.chunk_overlap_chars
    MAX_CHUNK_CHARS       = _b.max_chunk_chars
except Exception:
                                                                    
                                                                   
    DEFAULT_TARGET_CHARS = 1500
    DEFAULT_OVERLAP_CHARS = 200
    MAX_CHUNK_CHARS = 8000                                            

                                                       
_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_END_RE = re.compile(r"[.?!](?=\s|$)")
_WORD_BOUNDARY_RE = re.compile(r"\s")


@dataclass(frozen=True)
class Chunk:


    chunk_index: int
    char_start: int
    char_end: int
    text: str
    extraction_source: str

    @property
    def char_length(self) -> int:
        return self.char_end - self.char_start


def chunk_extracted_text(
    text: str,
    *,
    extraction_source: str,
    target_chars: int = DEFAULT_TARGET_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    max_chunk_chars: int = MAX_CHUNK_CHARS,
) -> list[Chunk]:


    if not text or not text.strip():
        return []
    if target_chars <= 0:
        raise ValueError("target_chars must be > 0")
    if overlap_chars < 0 or overlap_chars >= target_chars:
        raise ValueError("overlap_chars must be in [0, target_chars)")
    if max_chunk_chars < target_chars:
        raise ValueError("max_chunk_chars must be >= target_chars")

    chunks: list[Chunk] = []
    n = len(text)
    cursor = 0
    idx = 0
    while cursor < n:
                                                                 
                                                                 
        while cursor < n and text[cursor].isspace():
            cursor += 1
        if cursor >= n:
            break

        soft_end = min(cursor + target_chars, n)
        hard_end = min(cursor + max_chunk_chars, n)
        end, advance_to, hard_boundary = _pick_boundary(
            text, cursor, soft_end, hard_end,
        )

                                                                    
        actual_text = text[cursor:end].rstrip()
        if not actual_text:
                                                                       
            cursor = advance_to if advance_to > cursor else cursor + 1
            continue

        chunks.append(
            Chunk(
                chunk_index=idx,
                char_start=cursor,
                char_end=cursor + len(actual_text),
                text=actual_text,
                extraction_source=extraction_source,
            )
        )
        idx += 1
        if advance_to >= n:
            break
        if hard_boundary:
                                                                    
                                                                    
            next_cursor = advance_to
        else:
                                                                   
                                                                    
            next_cursor = end - overlap_chars
        cursor = max(cursor + 1, next_cursor)
    return chunks


def _pick_boundary(
    text: str, start: int, soft_end: int, hard_end: int,
) -> tuple[int, int, bool]:


    if soft_end >= len(text):
        return len(text), len(text), False
    window_start = start

                                                               
    para_match = _last_match_in_range(
        _PARAGRAPH_RE, text, window_start, soft_end,
    )
    if para_match is not None:
                                                                   
        return para_match.start(), para_match.end(), True

                                                            
    sent_match = _last_match_in_range(
        _SENTENCE_END_RE, text, window_start, soft_end,
    )
    if sent_match is not None:
        end = sent_match.end()
        return end, end, False

                                                                     
    for i in range(soft_end - 1, window_start, -1):
        if text[i].isspace():
            return i, i, False

                                                                       
    return soft_end, soft_end, False


def _last_match_in_range(
    pattern: "re.Pattern[str]",
    text: str,
    start: int,
    end: int,
):


    found = None
    for m in pattern.finditer(text, start, end):
        if m.end() > end:
            break
        found = m
    return found


def chunks_to_dicts(chunks: Iterable[Chunk]) -> list[dict]:


    return [
        {
            "chunk_index":       int(c.chunk_index),
            "char_start":        int(c.char_start),
            "char_end":          int(c.char_end),
            "text":              str(c.text),
            "extraction_source": str(c.extraction_source),
        }
        for c in chunks
    ]


__all__ = [
    "Chunk",
    "chunk_extracted_text",
    "chunks_to_dicts",
    "DEFAULT_TARGET_CHARS",
    "DEFAULT_OVERLAP_CHARS",
    "MAX_CHUNK_CHARS",
]
