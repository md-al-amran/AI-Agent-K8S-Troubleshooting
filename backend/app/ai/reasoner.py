"""Root Cause Analyzer: the AI Kubernetes Agent's main entry point.

Flow:
  investigation evidence
    -> Prompt Builder (structured SRE prompt)
    -> LLM Client (OpenRouter)
    -> parse and validate the JSON answer (root cause per issue)
    -> Fix Recommendation Engine (clean and check commands)
    -> Confidence Engine (check the score against the evidence)
    -> Diagnosis
"""

import json
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from app.ai.confidence import score_issue
from app.ai.fixes import refine_fix
from app.ai.llm_client import LLMError, chat_completion
from app.ai.prompt_builder import build_evidence, build_messages
from app.core.config import get_settings
from app.models.diagnosis import Diagnosis, IssueDiagnosis
from app.models.investigation import Investigation


HEALTHY_SUMMARY = "No critical Kubernetes issues detected. Cluster appears healthy."

_FORMAT_HINTS = [
    "Investigate again (models sometimes answer in the wrong format)",
    "If it keeps happening, pick a stronger model in OPENROUTER_MODEL",
]


class _ModelAnswer(BaseModel):
    """The JSON shape the system prompt asks the model for."""

    healthy: bool = False
    summary: str = ""
    issues: list[IssueDiagnosis] = Field(default_factory=list)


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the model reply, tolerating ```json fences or text around the object."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("The AI answered in an unexpected format.", _FORMAT_HINTS)
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError("The AI answered in an unexpected format.", _FORMAT_HINTS) from exc


def _healthy_diagnosis(summary: str, model: str | None) -> Diagnosis:
    return Diagnosis(
        healthy=True,
        summary=summary,
        title="Cluster healthy",
        severity="low",
        root_cause="No failing pods, deployments, or services were found.",
        confidence=90,
        confidence_level="high",
        confidence_reasons=["All pods, deployments, and services passed every check"],
        model=model,
    )


def diagnose(investigation: Investigation) -> Diagnosis:
    """Find the root cause of the problems in the evidence and suggest fixes."""
    summary = investigation.summary

    # Nothing to explain: skip the LLM call (saves time and cost).
    if summary.healthy and summary.warning_events == 0:
        logger.info("Cluster is healthy, no AI call needed")
        return _healthy_diagnosis(HEALTHY_SUMMARY, model=None)

    model = get_settings().openrouter_model
    reply = chat_completion(build_messages(investigation))

    try:
        answer = _ModelAnswer.model_validate(_extract_json(reply))
    except ValidationError as exc:
        logger.error("Model reply did not match the diagnosis shape: {}", exc.errors()[:3])
        raise LLMError("The AI answered in an unexpected format.", _FORMAT_HINTS) from exc

    if not answer.issues:
        return _healthy_diagnosis(answer.summary or HEALTHY_SUMMARY, model=model)

    evidence_text = build_evidence(investigation)
    issues = [score_issue(refine_fix(issue), investigation, evidence_text) for issue in answer.issues]
    primary, others = issues[0], issues[1:]

    logger.info(
        "Diagnosis: {} issue(s), primary '{}' at {}% confidence",
        len(issues),
        primary.title,
        primary.confidence,
    )
    return Diagnosis(
        **primary.model_dump(),
        healthy=False,
        summary=answer.summary,
        other_issues=others,
        model=model,
    )
