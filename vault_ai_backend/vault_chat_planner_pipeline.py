

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from vault_followup_classifier import (
    classify_followup,
    FollowupClassification,
    INTENT_NOT_A_FOLLOWUP,
    INTENT_PURE_REFERENT,
)
from vault_answer_planner import (
    plan_answer,
    AnswerPlan,
    ACTION_CANT_CONFIRM,
)
from vault_result_context import LastAssistantResult, get_last_assistant_result


logger = logging.getLogger(__name__)


EmbedFn = Callable[[str], Awaitable[Optional[list[float]]]]
LlmFollowupFn = Callable[
    [str, Optional[dict]], Awaitable[Optional[dict]],
]
CoverageLoader = Callable[[str], dict]
DaemonActiveProbe = Callable[[], bool]


@dataclass(frozen=True)
class PipelineDecision:


    handled: bool
    reply_body: str = ""
    delegate_to_regex_resolver: bool = False
    classification: Optional[FollowupClassification] = None
    plan: Optional[AnswerPlan] = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "handled":                     bool(self.handled),
            "reply_body":                  str(self.reply_body),
            "delegate_to_regex_resolver":  bool(self.delegate_to_regex_resolver),
            "classification":              (self.classification.to_dict()
                                            if self.classification else None),
            "plan":                        (self.plan.to_dict()
                                            if self.plan else None),
            "reason":                      str(self.reason),
        }


async def run_pipeline(
    *,
    vault_id: str,
    message: str,
    embed_fn: EmbedFn,
    coverage_loader: CoverageLoader,
    daemon_active_probe: DaemonActiveProbe,
    llm_fallback_fn: Optional[LlmFollowupFn] = None,
    last_result_override: Optional[LastAssistantResult] = None,
) -> PipelineDecision:


    if last_result_override is not None:
        last_result = last_result_override
    else:
        try:
            last_result = get_last_assistant_result(vault_id)
        except Exception:
            logger.exception("pipeline: get_last_assistant_result raised")
            last_result = None

    if last_result is None:
        return PipelineDecision(
            handled=False,
            reason="no_last_result",
        )

                                                                       
    summary = {
        "result_type":         last_result.result_type,
        "intent":              last_result.intent,
        "total_matches_known": last_result.total_matches_known,
        "is_partial":          last_result.is_partial,
                                                                     
                                                                
    }

                                
    try:
        classification = await classify_followup(
            message,
            embed_fn=embed_fn,
            llm_fallback_fn=llm_fallback_fn,
            last_result_summary=summary,
        )
    except Exception:
        logger.exception("pipeline: classify_followup raised")
        return PipelineDecision(
            handled=False,
            reason="classifier_raised",
        )

                                                            
    if classification.intent == INTENT_NOT_A_FOLLOWUP:
        return PipelineDecision(
            handled=False,
            classification=classification,
            reason="intent_not_followup",
        )

                                                                       
    if classification.intent == INTENT_PURE_REFERENT:
        return PipelineDecision(
            handled=False,
            delegate_to_regex_resolver=True,
            classification=classification,
            reason="intent_pure_referent_delegated",
        )

                                                    
    try:
        coverage = coverage_loader(vault_id)
    except Exception:
        logger.exception("pipeline: coverage_loader raised")
        coverage = {}
    try:
        daemon_active = bool(daemon_active_probe())
    except Exception:
        daemon_active = False

    plan = plan_answer(
        message=message,
        followup_intent=classification.intent,
        last_result=last_result,
        coverage=coverage,
        daemon_active=daemon_active,
    )

                                                             
    return PipelineDecision(
        handled=True,
        reply_body=plan.body,
        classification=classification,
        plan=plan,
        reason=plan.reason or classification.intent,
    )


__all__ = [
    "PipelineDecision",
    "run_pipeline",
]
