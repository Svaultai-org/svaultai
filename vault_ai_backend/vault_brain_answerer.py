

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from vault_evidence_bundle import EvidenceBundle, EvidenceChunk
from vault_brain_intent import (
    BRAIN_INTENTS,
    SEARCH_VAULT_CONTENT,
    ANSWER_FROM_VAULT_CONTENT,
    ANSWER_FROM_FILE_CONTENT,
    SUMMARIZE_FILE_CONTENT,
    SUMMARIZE_FOLDER_CONTENT,
    CREDENTIAL_LOOKUP,
)


logger = logging.getLogger(__name__)


COPY_NO_EVIDENCE = (
    "I couldn't find matching vault content for that."
)
COPY_PENDING_HINT = (
    "Some files are still pending analysis."
)
COPY_FAILED_HINT = (
    "Some files failed analysis and were skipped."
)
COPY_UNSUPPORTED_HINT = (
    "Some files are in unsupported formats and weren't indexed."
)

                                                                 
COPY_BRAIN_STILL_INDEXING = (
    "Your vault brain is still indexing files — "
    "I answered from what's already indexed."
)
COPY_BRAIN_FULLY_INDEXED = (
    "Your vault brain is fully indexed."
)
COPY_BRAIN_HAS_FAILURES = (
    "Some files failed indexing — "
    "they were excluded from the answer."
)
COPY_BRAIN_LEXICAL_FALLBACK = (
    "I'm using a text-substring search this turn — "
    "the semantic index is temporarily unavailable."
)


try:
    from vault_config import brain as _brain_cfg
    _b = _brain_cfg()
    DEFAULT_MAX_EVIDENCE_ROWS = _b.max_context_chunks
    DEFAULT_SNIPPET_CHARS = _b.evidence_snippet_chars
except Exception:
    DEFAULT_MAX_EVIDENCE_ROWS = 5
    DEFAULT_SNIPPET_CHARS = 240


@dataclass(frozen=True)
class EvidenceRow:


    file_id:           str
    file_name:         str
    snippet:           str
    extraction_source: str
    score:             float
    chunk_index:       int

    def to_dict(self) -> dict:
        return {
            "file_id":           str(self.file_id),
            "file_name":         str(self.file_name),
            "snippet":           str(self.snippet),
            "extraction_source": str(self.extraction_source),
            "score":             float(self.score),
            "chunk_index":       int(self.chunk_index),
        }


@dataclass(frozen=True)
class BrainAnswer:


    handled:        bool
    reply_body:     str
    evidence_rows:  tuple[EvidenceRow, ...] = field(default_factory=tuple)
    intent:         str = ""
    no_evidence:    bool = False
    coverage_note:  str = ""
    reason:         str = ""

    def to_dict(self) -> dict:
        return {
            "handled":       bool(self.handled),
            "reply_body":    str(self.reply_body),
            "evidence_rows": [r.to_dict() for r in self.evidence_rows],
            "intent":        str(self.intent),
            "no_evidence":   bool(self.no_evidence),
            "coverage_note": str(self.coverage_note),
            "reason":        str(self.reason),
        }


def _lookup_file_names(file_ids: list[str]) -> dict[str, str]:


    if not file_ids:
        return {}
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, file_name, saved_name
            FROM uploaded_files
            WHERE id = ANY(%s)
            """,
            (list(file_ids),),
        )
        rows = cur.fetchall() or []
    except Exception:
        logger.exception("[BRAIN-ANSWER] file_name lookup failed")
        rows = []
    finally:
        conn.close()
    out: dict[str, str] = {}
    for row in rows:
        fid = str(row[0])
        fname = row[1] or row[2] or fid[:8] + "…"
        out[fid] = str(fname)
    return out


def _lookup_file_content_hashes(file_ids: list[str]) -> dict[str, str]:


    if not file_ids:
        return {}
    try:
        from vault_core import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, COALESCE(content_sha256, '')
                FROM uploaded_files
                WHERE id = ANY(%s)
                """,
                (list(file_ids),),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "[BRAIN-ANSWER] content_sha256 lookup failed",
        )
        return {}
    return {str(r[0]): str(r[1] or "").lower() for r in rows}


def _truncate_snippet(text: str, *, max_chars: int) -> str:
    if not text:
        return ""
    t = str(text).strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip() + "…"


_WORD_RE = __import__("re").compile(r"[a-z0-9']{3,}")
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "it", "of", "to", "in", "and", "or",
    "i", "you", "me", "we", "us", "my", "your", "do", "did",
    "does", "have", "has", "had", "that", "this", "those", "these",
    "be", "been", "about", "any", "anything", "what", "which",
    "where", "when", "who", "why", "how", "for", "on", "at", "by",
    "from", "with", "as", "but", "not", "are", "was", "were",
    "can", "could", "should", "would", "shall", "will",
    "find", "search", "show", "list", "tell", "say", "saved",
    "mention", "mentions", "files", "file", "document", "documents",
    "anything", "something", "stuff", "things", "thing",
})


def _window_snippet(
    text: str, *, query: str, max_chars: int,
) -> str:


    if not text:
        return ""
    raw = str(text)
    if len(raw) <= max_chars:
        return raw.strip()
    lowered = raw.lower()
    keywords = [
        w for w in _WORD_RE.findall((query or "").lower())
        if w not in _STOPWORDS
    ]
    best_pos = -1
    for kw in keywords:
        p = lowered.find(kw)
        if p == -1:
            continue
        if best_pos == -1 or p < best_pos:
            best_pos = p
    if best_pos == -1:
        return _truncate_snippet(raw, max_chars=max_chars)
                                         
    half = max_chars // 2
    start = max(0, best_pos - half + len("blue") // 2)
    end = min(len(raw), start + max_chars)
                                                                
                                            
    if start > 0:
                                                              
        space = raw.rfind(" ", 0, start)
        if space != -1 and start - space < 40:
            start = space + 1
    snippet = raw[start:end].strip()
    prefix = "" if start == 0 else "…"
    suffix = "" if end == len(raw) else "…"
    return f"{prefix}{snippet}{suffix}"


def _build_evidence_rows(
    bundle: EvidenceBundle,
    *,
    file_names: dict[str, str],
    max_rows: int,
    snippet_chars: int,
) -> tuple[EvidenceRow, ...]:


    query = bundle.query or ""

                                                               
    best_per_file: dict[str, EvidenceRow] = {}
    file_order: list[str] = []
    for ch in bundle.chunks:
        fid = str(ch.file_id)
        candidate = EvidenceRow(
            file_id=fid,
            file_name=file_names.get(fid, fid[:8] + "…"),
            snippet=_window_snippet(
                ch.text, query=query, max_chars=snippet_chars,
            ),
            extraction_source=str(ch.extraction_source),
            score=float(ch.score),
            chunk_index=int(ch.chunk_index),
        )
        existing = best_per_file.get(fid)
        if existing is None:
            best_per_file[fid] = candidate
            file_order.append(fid)
        elif candidate.score > existing.score:
            best_per_file[fid] = candidate

                                                              
    hashes = _lookup_file_content_hashes(file_order)
    sha_seen: set[str] = set()
    deduped: list[EvidenceRow] = []
    for fid in file_order:
        sha = hashes.get(fid) or ""
        if sha and sha in sha_seen:
            continue
        if sha:
            sha_seen.add(sha)
        deduped.append(best_per_file[fid])
        if len(deduped) >= max_rows:
            break
    return tuple(deduped)


def _coverage_note(bundle: EvidenceBundle) -> str:


    if bundle.excluded_pending > 0:
        return COPY_PENDING_HINT
    if bundle.excluded_failed > 0:
        return COPY_FAILED_HINT
    if bundle.excluded_unsupported > 0:
        return COPY_UNSUPPORTED_HINT
    return ""


def _brain_coverage_note(brain_coverage, retrieval_mode: str = "") -> str:


    note_parts: list[str] = []
    if retrieval_mode in (
        "lexical_fallback", "chunk_text_lexical",
    ):
        note_parts.append(COPY_BRAIN_LEXICAL_FALLBACK)
    if brain_coverage is None:
        return " ".join(note_parts).strip()
    try:
        is_complete = bool(brain_coverage.is_complete)
        has_failures = bool(brain_coverage.has_failures)
    except Exception:
        return " ".join(note_parts).strip()
    if has_failures:
        note_parts.append(COPY_BRAIN_HAS_FAILURES)
    if not is_complete:
        note_parts.append(COPY_BRAIN_STILL_INDEXING)
    return " ".join(note_parts).strip()


def _compose_search_body(
    bundle: EvidenceBundle,
    evidence_rows: tuple[EvidenceRow, ...],
) -> str:


    if not evidence_rows:
        return COPY_NO_EVIDENCE
    unique_files: list[str] = []
    for r in evidence_rows:
        if r.file_name not in unique_files:
            unique_files.append(r.file_name)
    if len(unique_files) == 1:
        head = f"Yes — I found this in **{unique_files[0]}**:"
    else:
        joined = ", ".join(f"**{n}**" for n in unique_files[:5])
        head = f"Yes — I found matches across {len(unique_files)} files: {joined}."
                                                                
                                                                    
    snippet = _truncate_snippet(evidence_rows[0].snippet, max_chars=400)
    return f"{head}\n\n> {snippet}"


def _compose_answer_body(
    bundle: EvidenceBundle,
    evidence_rows: tuple[EvidenceRow, ...],
) -> str:


    if not evidence_rows:
        return COPY_NO_EVIDENCE
    top = evidence_rows[0]
    return (
        f"From **{top.file_name}**:\n\n> {top.snippet}"
    )


def _compose_summary_body(
    bundle: EvidenceBundle,
    evidence_rows: tuple[EvidenceRow, ...],
    *,
    is_folder: bool,
) -> str:


    if not evidence_rows:
        return COPY_NO_EVIDENCE
    header = (
        "Here are the top excerpts from that folder:"
        if is_folder else
        "Here are the top excerpts from that file:"
    )
    body_lines = [header, ""]
    for r in evidence_rows[:3]:
        body_lines.append(f"From **{r.file_name}**: {r.snippet}")
        body_lines.append("")
    return "\n".join(body_lines).rstrip()


def _compose_credential_body(
    bundle: EvidenceBundle,
    evidence_rows: tuple[EvidenceRow, ...],
) -> str:


    if not evidence_rows:
        return COPY_NO_EVIDENCE
    try:
        from extractor import extract_multiple_credentials
    except Exception:
                                                                
                                                             
        return _compose_answer_body(bundle, evidence_rows)
    services_seen: list[str] = []
    verified_count = 0
    for ch in bundle.chunks:
        extracted = extract_multiple_credentials(ch.text or "") or []
        for cred in extracted:
            svc = (cred.get("service") or "general").strip()
            if not svc:
                continue
            svc_pretty = svc.title()
            if svc_pretty not in services_seen:
                services_seen.append(svc_pretty)
            verified_count += 1
    if not services_seen:
                                                                   
                                                              
        top = evidence_rows[0]
        return (
            f"I found this in **{top.file_name}**, but it doesn't "
            f"look like a saved credential:\n\n> {top.snippet}"
        )
    unique_files = []
    for r in evidence_rows:
        if r.file_name not in unique_files:
            unique_files.append(r.file_name)
    file_count = len(unique_files) or len(bundle.matching_file_ids)
    file_word = "file" if file_count == 1 else "files"
    record_word = "record" if verified_count == 1 else "records"
    head = (
        f"I found credential records in {file_count} {file_word} "
        f"from the indexed vault memory."
    )
    detail = f" Verified {verified_count} credential-shaped {record_word}."
    if services_seen:
        joined = ", ".join(f"**{s}**" for s in services_seen[:5])
        detail += f" Services detected: {joined}."
    files_line = ""
    if unique_files:
        files_line = (
            "\n\nFiles: "
            + ", ".join(f"**{n}**" for n in unique_files[:8])
        )
    return head + detail + files_line


def compose_brain_answer(
    *,
    intent: str,
    bundle: EvidenceBundle,
    max_rows: int = DEFAULT_MAX_EVIDENCE_ROWS,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    file_name_lookup=None,
    brain_coverage=None,
    breadth: str = "",
) -> BrainAnswer:


    if intent not in BRAIN_INTENTS:
        return BrainAnswer(
            handled=False,
            reply_body="",
            intent=intent,
            reason="non_brain_intent",
        )

                                                                
    effective_max_rows = max_rows
    if breadth in ("broad",):
        try:
            from vault_config import brain as _bcfg
            effective_max_rows = max(
                max_rows, _bcfg().max_files_per_query,
            )
        except Exception:
            effective_max_rows = max(max_rows, 12)
    elif breadth in ("summary",):
        try:
            from vault_config import brain as _bcfg
            effective_max_rows = max(
                max_rows, _bcfg().summary_max_chunks // 4,
            )
        except Exception:
            effective_max_rows = max(max_rows, 10)

                                                               
    file_ids = list(bundle.matching_file_ids)
    if file_name_lookup is None:
        file_names = _lookup_file_names(file_ids)
    else:
        file_names = file_name_lookup(file_ids) or {}

    evidence_rows = _build_evidence_rows(
        bundle,
        file_names=file_names,
        max_rows=effective_max_rows,
        snippet_chars=snippet_chars,
    )

    if intent == SEARCH_VAULT_CONTENT:
        body = _compose_search_body(bundle, evidence_rows)
    elif intent == ANSWER_FROM_FILE_CONTENT:
        body = _compose_answer_body(bundle, evidence_rows)
    elif intent == SUMMARIZE_FILE_CONTENT:
        body = _compose_summary_body(
            bundle, evidence_rows, is_folder=False,
        )
    elif intent == SUMMARIZE_FOLDER_CONTENT:
        body = _compose_summary_body(
            bundle, evidence_rows, is_folder=True,
        )
    elif intent == CREDENTIAL_LOOKUP:
        body = _compose_credential_body(bundle, evidence_rows)
    else:                             
        body = _compose_answer_body(bundle, evidence_rows)

    no_evidence = not evidence_rows

                                                        
    legacy_note = _coverage_note(bundle)
    brain_note  = _brain_coverage_note(
        brain_coverage, retrieval_mode=str(bundle.retrieval_mode or ""),
    )
    notes = [n for n in (brain_note, legacy_note) if n]
    coverage_note = " ".join(notes).strip()
    if coverage_note:
        body = body + "\n\n" + coverage_note

    return BrainAnswer(
        handled=True,
        reply_body=body,
        evidence_rows=evidence_rows,
        intent=intent,
        no_evidence=no_evidence,
        coverage_note=coverage_note,
        reason="composed",
    )


__all__ = [
    "BrainAnswer",
    "EvidenceRow",
    "COPY_NO_EVIDENCE",
    "COPY_PENDING_HINT",
    "COPY_FAILED_HINT",
    "COPY_UNSUPPORTED_HINT",
    "COPY_BRAIN_STILL_INDEXING",
    "COPY_BRAIN_FULLY_INDEXED",
    "COPY_BRAIN_HAS_FAILURES",
    "COPY_BRAIN_LEXICAL_FALLBACK",
    "DEFAULT_MAX_EVIDENCE_ROWS",
    "DEFAULT_SNIPPET_CHARS",
    "compose_brain_answer",
]
