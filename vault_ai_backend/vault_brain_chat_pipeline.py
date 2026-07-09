

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from vault_brain_intent import (
    classify_brain_intent,
    BrainIntent,
    BRAIN_INTENTS,
    NOT_VAULT_CONTENT,
)
from vault_brain_answerer import (
    BrainAnswer,
    EvidenceRow,
    compose_brain_answer,
    DEFAULT_MAX_EVIDENCE_ROWS,
    DEFAULT_SNIPPET_CHARS,
)
from vault_evidence_bundle import EvidenceBundle, empty_bundle


logger = logging.getLogger(__name__)


REASON_NOT_VAULT_CONTENT  = "not_vault_content"
REASON_RETRIEVAL_RAISED   = "retrieval_raised"
REASON_RETRIEVAL_EMPTY    = "retrieval_empty"
REASON_BUNDLE_COMPOSED    = "bundle_composed"
REASON_PIPELINE_DISABLED  = "pipeline_disabled"


EmbedFn = Callable[[str], Awaitable[Optional[list[float]]]]
RetrieveFn = Callable[..., Awaitable[EvidenceBundle]]
GroundedAnswerComposeFn = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class BrainPipelineDecision:


    handled:                 bool
    reply_body:              str = ""
    evidence_rows:           tuple[EvidenceRow, ...] = field(default_factory=tuple)
    intent:                  str = ""
    no_evidence:             bool = False
    retrieval_mode:          str = ""
    breadth:                 str = ""
    coverage_note:           str = ""
    brain_coverage_dict:     dict = field(default_factory=dict)
    continuation_available:  bool = False
    reason:                  str = ""
    debug:                   dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "handled":                bool(self.handled),
            "reply_body":             str(self.reply_body),
            "evidence_rows":          [r.to_dict() for r in self.evidence_rows],
            "intent":                 str(self.intent),
            "no_evidence":            bool(self.no_evidence),
            "retrieval_mode":         str(self.retrieval_mode),
            "breadth":                str(self.breadth),
            "coverage_note":          str(self.coverage_note),
            "brain_coverage_dict":    dict(self.brain_coverage_dict),
            "continuation_available": bool(self.continuation_available),
            "reason":                 str(self.reason),
            "debug":                  dict(self.debug),
        }


async def run_brain_chat_pipeline(
    *,
    vault_id: str,
    message: str,
    key: bytes,
    embed_fn: EmbedFn,
    coverage: dict,
    pending_file_present: bool = False,
    has_uploaded_files_in_turn: bool = False,
    retrieve_fn: Optional[RetrieveFn] = None,
    file_name_lookup=None,
    max_rows: int = DEFAULT_MAX_EVIDENCE_ROWS,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    top_k: Optional[int] = None,
    min_similarity: Optional[float] = None,
    brain_coverage_loader=None,
    continuation_loader=None,
    continuation_setter=None,
    grounded_answer_client=None,
    grounded_answer_compose_fn: Optional[GroundedAnswerComposeFn] = None,
    now_unix: Optional[float] = None,
) -> BrainPipelineDecision:


    if not message or not str(message).strip():
        return BrainPipelineDecision(
            handled=False,
            reason="empty_message",
        )

                                                                  
    if brain_coverage_loader is None:
        try:
            from vault_brain_coverage import brain_coverage_for_vault as _bcfv
            brain_coverage_loader = _bcfv
        except Exception:
            brain_coverage_loader = None
    if continuation_loader is None:
        try:
            from vault_brain_continuation import get_last_brain_evidence as _gle
            continuation_loader = _gle
        except Exception:
            continuation_loader = None
    if continuation_setter is None:
        try:
            from vault_brain_continuation import set_last_brain_evidence as _sle
            continuation_setter = _sle
        except Exception:
            continuation_setter = None

    try:
        brain_coverage = (
            brain_coverage_loader(vault_id)
            if brain_coverage_loader else None
        )
    except Exception:
        logger.warning(
            "[BRAIN-CHAT] brain_coverage_loader raised vault=%s",
            (vault_id or "")[:8] + "…",
        )
        brain_coverage = None

                                                                  
    if brain_coverage is not None:
        try:
            _indexed_count = int(
                getattr(brain_coverage, "files_with_all_chunks_embedded", 0)
                or 0
            )
        except Exception:
            _indexed_count = 0
        try:
            _total_files = int(
                getattr(brain_coverage, "total_files", 0) or 0
            )
        except Exception:
            _total_files = 0
                                                                  
                                                           
        if _indexed_count <= 0 and _total_files > 0:
            logger.info(
                "[BRAIN-CHAT] brain_not_indexed_yet vault=%s indexed=0",
                (vault_id or "")[:8] + "…",
            )
            return BrainPipelineDecision(
                handled=False,
                reason="brain_not_indexed_yet",
            )

    try:
        prior_continuation = (
            continuation_loader(vault_id)
            if continuation_loader else None
        )
    except Exception:
        prior_continuation = None
    has_continuation_context = prior_continuation is not None

                                                                     
    classification: BrainIntent = classify_brain_intent(
        message,
        pending_file_present=pending_file_present,
        has_uploaded_files_in_turn=has_uploaded_files_in_turn,
        has_continuation_context=has_continuation_context,
    )
    if classification.intent == NOT_VAULT_CONTENT:
        return BrainPipelineDecision(
            handled=False,
            intent=classification.intent,
            reason=REASON_NOT_VAULT_CONTENT,
            continuation_available=has_continuation_context,
            debug={"classification": classification.to_dict()},
        )

                                                             
    try:
        from vault_brain_breadth import (
            classify_brain_breadth,
            BREADTH_NARROW, BREADTH_BROAD, BREADTH_SUMMARY,
            BREADTH_CONTINUATION,
        )
        breadth_decision = classify_brain_breadth(
            message,
            has_continuation_context=has_continuation_context,
        )
        breadth = breadth_decision.breadth
    except Exception:
        breadth = "narrow"
        breadth_decision = None

                                                                        
    if classification.intent == "continue_last_search":
        breadth = "continuation"

                                                                     
    if retrieve_fn is None:
        if classification.intent == "credential_lookup":
            from vault_brain_retrieval import (
                retrieve_credential_evidence as _retrieve,
            )
        else:
            from vault_brain_retrieval import retrieve_evidence as _retrieve
        retrieve_fn = _retrieve

    use_prior_query_context = (
        prior_continuation is not None
        and classification.reason == "credential_coverage_followup"
    )
    retrieval_kwargs = {
        "vault_id": vault_id,
        "query":    (
            prior_continuation.query_prefix
            if (
                (breadth == "continuation" and prior_continuation)
                or use_prior_query_context
            )
            else message
        ),
        "key":      key,
        "embed_fn": embed_fn,
        "coverage": coverage,
        "breadth":  breadth,
    }
    if top_k is not None:
        retrieval_kwargs["top_k"] = int(top_k)
    if min_similarity is not None:
        retrieval_kwargs["min_similarity"] = float(min_similarity)
    if breadth == "continuation" and prior_continuation:
                                                                    
                                                                   
        retrieval_kwargs["excluded_chunk_ids"] = tuple(
            prior_continuation.chunk_ids_returned
        )
        retrieval_kwargs["excluded_file_ids"] = tuple(
            prior_continuation.file_ids_returned
        )

    try:
        bundle = await retrieve_fn(**retrieval_kwargs)
    except TypeError:
                                                                    
                                                                   
        legacy_kwargs = {
            k: v for k, v in retrieval_kwargs.items()
            if k in ("vault_id", "query", "key",
                     "embed_fn", "coverage",
                     "top_k", "min_similarity")
        }
        try:
            bundle = await retrieve_fn(**legacy_kwargs)
        except Exception:
            logger.exception(
                "[BRAIN-CHAT] retrieve_evidence raised vault=%s",
                (vault_id or "")[:8] + "…",
            )
            bundle = empty_bundle(
                query=message, vault_id=vault_id, coverage=coverage,
                error="retrieval_raised",
            )
    except Exception:
                                                                           
        logger.exception(
            "[BRAIN-CHAT] retrieve_evidence raised vault=%s",
            (vault_id or "")[:8] + "…",
        )
        bundle = empty_bundle(
            query=message, vault_id=vault_id, coverage=coverage,
            error="retrieval_raised",
        )

                                                                   
    answer: BrainAnswer = compose_brain_answer(
        intent=(
            classification.intent
            if classification.intent != "continue_last_search"
                                                                
                                                                   
            else "search_vault_content"
        ),
        bundle=bundle,
        max_rows=max_rows,
        snippet_chars=snippet_chars,
        file_name_lookup=file_name_lookup,
        brain_coverage=brain_coverage,
        breadth=breadth,
    )

    final_reply_body = answer.reply_body
    if grounded_answer_compose_fn is None and grounded_answer_client is not None:
        try:
            from vault_memory_answer_composer import (
                compose_vault_memory_answer as _grounded_compose,
            )
            grounded_answer_compose_fn = _grounded_compose
        except Exception:
            grounded_answer_compose_fn = None
    if grounded_answer_compose_fn is not None:
        try:
            final_reply_body = await grounded_answer_compose_fn(
                openai_client=grounded_answer_client,
                user_question=message,
                intent=(
                    classification.intent
                    if classification.intent != "continue_last_search"
                    else "search_vault_content"
                ),
                bundle=bundle,
                evidence_rows=answer.evidence_rows,
                brain_coverage=brain_coverage,
                authorized_unlocked=True,
                result_type=classification.intent,
                allow_secret_reveal=False,
            )
        except Exception:
            logger.exception(
                "[BRAIN-CHAT] grounded_answer_compose failed vault=%s",
                (vault_id or "")[:8] + "â€¦",
            )
            final_reply_body = answer.reply_body

                                                        
    should_persist = (
        continuation_setter is not None
        and bundle.error is None
    )
    if should_persist:
        if now_unix is None:
            try:
                import time as _time
                now_unix = _time.time()
            except Exception:
                now_unix = 0.0
        try:
                                                                   
                                                                   
            prior_file_ids = (
                list(prior_continuation.file_ids_returned)
                if prior_continuation else []
            )
            prior_chunk_ids = (
                list(prior_continuation.chunk_ids_returned)
                if prior_continuation else []
            )
            new_file_ids  = list(bundle.matching_file_ids)
            new_chunk_ids = [
                str(c.chunk_id) for c in bundle.chunks
            ]
            combined_files  = list(dict.fromkeys(
                prior_file_ids + new_file_ids,
            ))
            combined_chunks = list(dict.fromkeys(
                prior_chunk_ids + new_chunk_ids,
            ))
            continuation_setter(
                vault_id=vault_id,
                query=(
                    prior_continuation.query_prefix
                    if (
                        (breadth == "continuation" and prior_continuation)
                        or use_prior_query_context
                    )
                    else message
                ),
                intent=classification.intent,
                breadth=breadth,
                file_ids_returned=combined_files,
                chunk_ids_returned=combined_chunks,
                coverage_at_time=dict(bundle.coverage_at_time or {}),
                retrieval_mode=str(bundle.retrieval_mode or ""),
                set_at_unix=float(now_unix or 0.0),
            )
        except TypeError:
                                                                      
                                                                       
            try:
                continuation_setter(
                    vault_id=vault_id,
                    query=(
                        prior_continuation.query_prefix
                        if (
                            (breadth == "continuation" and prior_continuation)
                            or use_prior_query_context
                        )
                        else message
                    ),
                    intent=classification.intent,
                    breadth=breadth,
                    file_ids_returned=combined_files,
                    coverage_at_time=dict(bundle.coverage_at_time or {}),
                    retrieval_mode=str(bundle.retrieval_mode or ""),
                    set_at_unix=float(now_unix or 0.0),
                )
            except Exception:
                logger.warning(
                    "[BRAIN-CHAT] continuation_setter (legacy retry) "
                    "failed vault=%s",
                    (vault_id or "")[:8] + "…",
                )
        except Exception:
            logger.warning(
                "[BRAIN-CHAT] continuation_setter failed vault=%s",
                (vault_id or "")[:8] + "…",
            )

    brain_coverage_dict = (
        brain_coverage.to_dict() if brain_coverage is not None else {}
    )

    return BrainPipelineDecision(
        handled=True,
        reply_body=final_reply_body,
        evidence_rows=answer.evidence_rows,
        intent=classification.intent,
        no_evidence=answer.no_evidence,
        retrieval_mode=str(bundle.retrieval_mode),
        breadth=breadth,
        coverage_note=answer.coverage_note,
        brain_coverage_dict=brain_coverage_dict,
                                                                 
                                                                    
        continuation_available=bool(bundle.matching_file_ids
                                    or has_continuation_context),
        reason=(
            REASON_RETRIEVAL_EMPTY
            if answer.no_evidence else REASON_BUNDLE_COMPOSED
        ),
        debug={
            "classification": classification.to_dict(),
            "bundle":         bundle.to_debug_dict(),
            "breadth":        (
                breadth_decision.to_dict() if breadth_decision else {}
            ),
            "brain_coverage": brain_coverage_dict,
        },
    )


__all__ = [
    "BrainPipelineDecision",
    "run_brain_chat_pipeline",
    "REASON_NOT_VAULT_CONTENT",
    "REASON_RETRIEVAL_RAISED",
    "REASON_RETRIEVAL_EMPTY",
    "REASON_BUNDLE_COMPOSED",
    "REASON_PIPELINE_DISABLED",
]
