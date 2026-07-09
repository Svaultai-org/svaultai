

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class EvidenceChunk:

    chunk_id:          str
    file_id:           str
    chunk_index:       int
    text:              str                                   
    extraction_source: str
    score:             float                                        
    char_start:        int
    char_end:          int


@dataclass(frozen=True)
class EvidenceBundle:


    query:                  str
    vault_id:               str
    chunks:                 tuple[EvidenceChunk, ...]
    matching_file_ids:      tuple[str, ...]
    coverage_at_time:       dict
    excluded_unsupported:   int = 0
    excluded_failed:        int = 0
    excluded_pending:       int = 0
    retrieval_mode:         str = "semantic"               
    error:                  Optional[str] = None

    @property
    def has_evidence(self) -> bool:
        return len(self.chunks) > 0

    @property
    def total_matching_files(self) -> int:
        return len(self.matching_file_ids)

    def snippets(self, *, max_chars: int = 240) -> list[str]:


        out: list[str] = []
        for c in self.chunks:
            t = c.text or ""
            if len(t) > max_chars:
                t = t[:max_chars].rstrip() + "…"
            out.append(t)
        return out

    def to_debug_dict(self) -> dict:


        return {
            "vault_id":             str(self.vault_id)[:8] + "…",
            "n_chunks":             len(self.chunks),
            "n_matching_files":     len(self.matching_file_ids),
            "retrieval_mode":       self.retrieval_mode,
            "excluded_unsupported": int(self.excluded_unsupported),
            "excluded_failed":      int(self.excluded_failed),
            "excluded_pending":     int(self.excluded_pending),
            "top_scores":           [
                round(float(c.score), 4) for c in self.chunks[:5]
            ],
            "extraction_sources":   sorted({
                c.extraction_source for c in self.chunks
            }),
            "error":                self.error,
        }


def empty_bundle(
    *, query: str, vault_id: str, coverage: dict,
    error: Optional[str] = None,
) -> EvidenceBundle:


    return EvidenceBundle(
        query=query,
        vault_id=vault_id,
        chunks=(),
        matching_file_ids=(),
        coverage_at_time=dict(coverage or {}),
        error=error,
    )


__all__ = [
    "EvidenceChunk",
    "EvidenceBundle",
    "empty_bundle",
]
