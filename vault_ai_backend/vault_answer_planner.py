

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from vault_followup_classifier import (
    INTENT_COVERAGE_COMPLETE_CHECK,
    INTENT_WANT_MORE_RESULTS,
    INTENT_CHECK_OTHER_LOCATIONS,
    INTENT_RERUN_WITH_DIFFERENT_FILTER,
    INTENT_PURE_REFERENT,
    INTENT_NOT_A_FOLLOWUP,
    FOLLOWUP_INTENTS,
)
from vault_result_context import LastAssistantResult


ACTION_FULL_ANSWER          = "FULL_ANSWER"
ACTION_PARTIAL_WITH_LIMITS  = "PARTIAL_WITH_LIMITS"
ACTION_WAIT_FOR_ANALYSIS    = "WAIT_FOR_ANALYSIS"
ACTION_CLARIFY              = "CLARIFY"
ACTION_CANT_CONFIRM         = "CANT_CONFIRM"

ACTIONS = (
    ACTION_FULL_ANSWER,
    ACTION_PARTIAL_WITH_LIMITS,
    ACTION_WAIT_FOR_ANALYSIS,
    ACTION_CLARIFY,
    ACTION_CANT_CONFIRM,
)


REASON_NO_LAST_RESULT          = "no_last_result"
REASON_INTENT_NOT_FOLLOWUP     = "intent_not_followup"
REASON_INTENT_PURE_REFERENT    = "intent_pure_referent_delegated"
REASON_COVERAGE_COMPLETE       = "coverage_complete"
REASON_COVERAGE_PARTIAL        = "coverage_partial"
REASON_COVERAGE_PARTIAL_DAEMON_ACTIVE = "coverage_partial_daemon_active"
REASON_NEED_FILTER_CHOICE      = "need_filter_choice"
REASON_NO_LOCATION_INDEX       = "no_location_index"


@dataclass(frozen=True)
class FactPack:


    match_count:        int
    result_was_partial: bool
    result_type:        str
                    
    total:              int
    analyzed:           int
    pending:            int
    not_started:        int
    processing:         int
    failed:             int
    unsupported:        int
    skipped:            int
    scan_complete:      bool
                  
    daemon_active:      bool

                                                                    
    @property
    def still_to_scan(self) -> int:
        return max(0, self.pending + self.not_started + self.processing)

    @property
    def has_pending(self) -> bool:
        return self.still_to_scan > 0

    @property
    def has_unsupported(self) -> bool:
        return self.unsupported > 0

    @property
    def has_failed(self) -> bool:
        return self.failed > 0

    @property
    def has_skipped(self) -> bool:
        return self.skipped > 0

    @property
    def is_honestly_complete(self) -> bool:
                                                                     
                                                     
        if self.scan_complete:
            return True
        if self.total == 0:
            return True
        if self.still_to_scan == 0:
            accounted = (
                self.analyzed + self.unsupported + self.failed + self.skipped
            )
            return accounted >= self.total
        return False


@dataclass(frozen=True)
class AnswerPlan:

    action:             str
    body:               str
    evidence_file_ids:  tuple[str, ...] = ()
    coverage_snapshot:  dict = field(default_factory=dict)
    followup_intent:    str = INTENT_NOT_A_FOLLOWUP
    reason:             str = ""
    clarification_options: tuple[str, ...] = ()
    facts:              Optional[FactPack] = None

    def to_dict(self) -> dict:
        return {
            "action":               str(self.action),
            "body":                 str(self.body),
            "evidence_file_ids":    list(self.evidence_file_ids),
            "coverage_snapshot":    dict(self.coverage_snapshot),
            "followup_intent":      str(self.followup_intent),
            "reason":               str(self.reason),
            "clarification_options": list(self.clarification_options),
        }


def _coverage_int(coverage: dict, *keys: str) -> int:
    for k in keys:
        v = coverage.get(k)
        if isinstance(v, (int, float)) and v == v:           
            return int(v)
    return 0


def facts_from_inputs(
    *,
    last_result: Optional[LastAssistantResult],
    coverage: dict,
    daemon_active: bool,
) -> FactPack:


    cov = coverage or {}
    return FactPack(
        match_count=(int(last_result.total_matches_known)
                     if last_result is not None else 0),
        result_was_partial=(bool(last_result.is_partial)
                            if last_result is not None else False),
        result_type=(str(last_result.result_type)
                     if last_result is not None else ""),
        total=_coverage_int(cov, "total"),
        analyzed=_coverage_int(cov, "analyzed", "scanned"),
        pending=_coverage_int(cov, "pending"),
        not_started=_coverage_int(cov, "not_started"),
        processing=_coverage_int(cov, "processing"),
        failed=_coverage_int(cov, "failed"),
        unsupported=_coverage_int(cov, "unsupported"),
        skipped=_coverage_int(cov, "skipped"),
        scan_complete=bool(cov.get("scan_complete")),
        daemon_active=bool(daemon_active),
    )


def _stmt_conclusion(facts: FactPack) -> Optional[str]:


    if facts.is_honestly_complete:
        if facts.total == 0:
            return "The vault is empty so there's nothing to check."
        if facts.match_count == 0:
            return (
                f"After checking all {facts.total} "
                f"{_files_word(facts.total)}, none matched."
            )
        return (
            f"After checking all {facts.total} "
            f"{_files_word(facts.total)}, I found "
            f"{facts.match_count} "
            f"{_matching_files_word(facts.match_count)}."
        )
                                
    if facts.daemon_active:
        return "Analysis is still running."
    return "I can't confirm this is complete yet."


def _stmt_progress(facts: FactPack) -> Optional[str]:


    if facts.total == 0:
        return None
    if facts.is_honestly_complete:
                                                              
                                               
        return None
    return (
        f"So far I've analyzed {facts.analyzed} of {facts.total} "
        f"{_files_word(facts.total)}."
    )


def _stmt_matches_so_far(facts: FactPack) -> Optional[str]:


    if facts.is_honestly_complete:
        return None
    if facts.match_count == 0:
        return "No matches found yet."
    return (
        f"Found {facts.match_count} "
        f"{_matching_files_word(facts.match_count)} so far."
    )


def _stmts_for_extras(facts: FactPack) -> list[str]:


    out: list[str] = []
    if facts.still_to_scan > 0:
        out.append(
            f"{facts.still_to_scan} "
            f"{_files_word(facts.still_to_scan)} "
            f"still to scan."
        )
    if facts.has_unsupported:
        out.append(
            f"{facts.unsupported} "
            f"{_files_word(facts.unsupported)} unsupported."
        )
    if facts.has_failed:
        out.append(
            f"{facts.failed} extraction "
            f"{('failure' if facts.failed == 1 else 'failures')}."
        )
    if facts.has_skipped:
        out.append(
            f"{facts.skipped} skipped."
        )
    return out


def compose_body(facts: FactPack) -> str:


    statements: list[str] = []
    for stmt in (
        _stmt_conclusion(facts),
        _stmt_progress(facts),
        _stmt_matches_so_far(facts),
    ):
        if stmt:
            statements.append(stmt)
    statements.extend(_stmts_for_extras(facts))
    return " ".join(statements).strip()


def _files_word(n: int) -> str:
    return "file" if n == 1 else "files"


def _matching_files_word(n: int) -> str:
    return "matching file" if n == 1 else "matching files"


def _body_no_last_result() -> str:


    return (
        "I don't have a previous result to compare against. "
        "Could you tell me which result you're asking about, "
        "or re-run the search?"
    )


def _body_cant_confirm_generic() -> str:
    return (
        "I can't answer that without more context. "
        "Could you re-ask with the specific file or folder you mean?"
    )


def _body_check_other_locations(facts: FactPack) -> str:
                                                 
    if facts.total == 0:
        return "The vault is empty so there are no other folders to check."
    return (
        f"The previous search ran across the whole vault — "
        f"all {facts.total} {_files_word(facts.total)}. "
        f"I don't keep a per-folder breakdown yet. "
        f"Name the folder you want filtered and I'll re-run."
    )


def _body_clarify_filter() -> str:
    return (
        "I can broaden the search. Which way did you have in mind?"
    )


def plan_answer(
    *,
    message: str,
    followup_intent: str,
    last_result: Optional[LastAssistantResult],
    coverage: dict,
    daemon_active: bool,
) -> AnswerPlan:


    if last_result is None:
        return AnswerPlan(
            action=ACTION_CANT_CONFIRM,
            body=_body_no_last_result(),
            followup_intent=followup_intent,
            reason=REASON_NO_LAST_RESULT,
        )

    if followup_intent == INTENT_NOT_A_FOLLOWUP:
        return AnswerPlan(
            action=ACTION_CANT_CONFIRM,
            body=_body_cant_confirm_generic(),
            followup_intent=followup_intent,
            reason=REASON_INTENT_NOT_FOLLOWUP,
        )

    if followup_intent == INTENT_PURE_REFERENT:
        return AnswerPlan(
            action=ACTION_CANT_CONFIRM,
            body="",                                            
            followup_intent=followup_intent,
            reason=REASON_INTENT_PURE_REFERENT,
        )

                                                               
    facts = facts_from_inputs(
        last_result=last_result,
        coverage=coverage,
        daemon_active=daemon_active,
    )

    if followup_intent in (
        INTENT_COVERAGE_COMPLETE_CHECK, INTENT_WANT_MORE_RESULTS,
    ):
                                                                    
        if facts.is_honestly_complete and not facts.result_was_partial:
            action = ACTION_FULL_ANSWER
            reason = REASON_COVERAGE_COMPLETE
        elif facts.daemon_active:
            action = ACTION_WAIT_FOR_ANALYSIS
            reason = REASON_COVERAGE_PARTIAL_DAEMON_ACTIVE
        else:
            action = ACTION_PARTIAL_WITH_LIMITS
            reason = REASON_COVERAGE_PARTIAL
        return AnswerPlan(
            action=action,
            body=compose_body(facts),
            evidence_file_ids=last_result.file_ids_returned,
            coverage_snapshot=dict(coverage or {}),
            followup_intent=followup_intent,
            reason=reason,
            facts=facts,
        )

    if followup_intent == INTENT_CHECK_OTHER_LOCATIONS:
        return AnswerPlan(
            action=ACTION_PARTIAL_WITH_LIMITS,
            body=_body_check_other_locations(facts),
            evidence_file_ids=last_result.file_ids_returned,
            coverage_snapshot=dict(coverage or {}),
            followup_intent=followup_intent,
            reason=REASON_NO_LOCATION_INDEX,
            facts=facts,
        )

    if followup_intent == INTENT_RERUN_WITH_DIFFERENT_FILTER:
        return AnswerPlan(
            action=ACTION_CLARIFY,
            body=_body_clarify_filter(),
            evidence_file_ids=last_result.file_ids_returned,
            coverage_snapshot=dict(coverage or {}),
            followup_intent=followup_intent,
            reason=REASON_NEED_FILTER_CHOICE,
            clarification_options=(
                "include weak matches",
                "include unsupported files",
                "include files inside archives",
            ),
            facts=facts,
        )

                                                                   
    return AnswerPlan(
        action=ACTION_CANT_CONFIRM,
        body=_body_cant_confirm_generic(),
        followup_intent=followup_intent,
        reason="unknown_followup_intent",
    )


__all__ = [
    "ACTIONS",
    "ACTION_FULL_ANSWER",
    "ACTION_PARTIAL_WITH_LIMITS",
    "ACTION_WAIT_FOR_ANALYSIS",
    "ACTION_CLARIFY",
    "ACTION_CANT_CONFIRM",
    "AnswerPlan",
    "FactPack",
    "facts_from_inputs",
    "compose_body",
    "plan_answer",
]
