"""Confidence Engine: check the model's confidence against the actual evidence.

The model proposes a score. This step can only lower it, never raise it:
- an issue about resources that do not appear in the evidence is likely made up
- an issue that cites no evidence is a guess
- missing investigation steps mean the picture is incomplete

It also adds plain facts from the evidence (pod state, restarts, log lines,
events) to the reasons, so the user can see why the score is what it is.
"""

from app.models.diagnosis import IssueDiagnosis
from app.models.investigation import Investigation

CAP_NOT_IN_EVIDENCE = 40
CAP_NO_EVIDENCE_CITED = 50
CAP_PARTLY_IN_EVIDENCE = 70
CAP_INCOMPLETE_INVESTIGATION = 75


def _resource_names(issue: IssueDiagnosis) -> list[str]:
    """'Deployment/default/payment-service' -> 'payment-service'."""
    return [r.rstrip("/").split("/")[-1] for r in issue.affected_resources if r.strip()]


def _level(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _supporting_facts(names: list[str], investigation: Investigation) -> list[str]:
    """Facts about pods that belong to the affected resources (pods are named after their deployment)."""
    facts: list[str] = []
    for pod in investigation.pods.problematic_pods:
        if not any(pod.name == n or pod.name.startswith(f"{n}-") for n in names):
            continue
        facts.append(f"Pod {pod.namespace}/{pod.name} is {pod.status} with {pod.restarts} restart(s)")

        log_lines = [
            f.line
            for c in investigation.logs.containers
            if c.pod == pod.name and c.namespace == pod.namespace
            for f in c.findings
            if f.category != "error"
        ]
        if log_lines:
            facts.append(f"Logs show: {log_lines[-1]}")

        events = [
            e for e in investigation.events.findings if e.namespace == pod.namespace and e.object == f"Pod/{pod.name}"
        ]
        if events:
            reasons = ", ".join(sorted({e.category or e.reason for e in events}))
            facts.append(f"{sum(e.count for e in events)} event(s) for this pod: {reasons}")
    return facts[:6]


def score_issue(issue: IssueDiagnosis, investigation: Investigation, evidence_text: str) -> IssueDiagnosis:
    score = max(0, min(100, issue.confidence))
    checks: list[str] = []

    def cap(limit: int, reason: str) -> None:
        nonlocal score
        if score > limit:
            score = limit
            checks.append(f"Lowered to {limit}: {reason}")

    names = _resource_names(issue)
    found = [n for n in names if n in evidence_text]
    if names and not found:
        cap(CAP_NOT_IN_EVIDENCE, "none of the affected resources appear in the collected evidence")
    elif len(found) < len(names):
        missing = ", ".join(n for n in names if n not in found)
        cap(CAP_PARTLY_IN_EVIDENCE, f"some affected resources are not in the evidence ({missing})")

    if not issue.evidence:
        cap(CAP_NO_EVIDENCE_CITED, "the diagnosis cites no specific evidence")

    failed = investigation.summary.failed_steps
    if failed:
        cap(CAP_INCOMPLETE_INVESTIGATION, f"evidence is incomplete ({', '.join(failed)} could not be collected)")

    reasons = list(dict.fromkeys(issue.confidence_reasons + _supporting_facts(found, investigation) + checks))
    return issue.model_copy(update={"confidence": score, "confidence_level": _level(score), "confidence_reasons": reasons})
