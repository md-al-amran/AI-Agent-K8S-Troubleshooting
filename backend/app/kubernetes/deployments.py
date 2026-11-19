"""Deployment Inspector: find deployments that are missing replicas or failing to roll out.

Source: kubectl get deployments -A -o json
"""

from typing import Any

from loguru import logger

from app.kubernetes.executor import get_json
from app.kubernetes.utils import shorten
from app.models.investigation import DeploymentCondition, DeploymentIssue, DeploymentsReport


def _conditions(status: dict[str, Any]) -> list[DeploymentCondition]:
    return [
        DeploymentCondition(
            type=c.get("type", "?"),
            status=c.get("status", "Unknown"),
            reason=c.get("reason"),
            message=shorten(c.get("message")),
        )
        for c in status.get("conditions", [])
    ]


def _inspect_deployment(deployment: dict[str, Any]) -> DeploymentIssue | None:
    meta = deployment.get("metadata", {})
    spec = deployment.get("spec", {})
    status = deployment.get("status", {})

    desired = spec.get("replicas", 1)
    ready = status.get("readyReplicas", 0)
    available = status.get("availableReplicas", 0)
    unavailable = status.get("unavailableReplicas", 0)
    updated = status.get("updatedReplicas", 0)
    conditions = _conditions(status)
    by_type = {c.type: c for c in conditions}
    issues: list[str] = []

    if desired == 0:
        return None  # scaled down on purpose

    if available < desired:
        issues.append(f"{desired - available} of {desired} replicas unavailable")

    progressing = by_type.get("Progressing")
    if progressing and progressing.status == "False":
        issues.append(f"Rollout failed: {progressing.reason or 'not progressing'}")

    available_condition = by_type.get("Available")
    if available_condition and available_condition.status == "False":
        issues.append(f"Deployment not available: {available_condition.reason or 'unknown reason'}")

    replica_failure = by_type.get("ReplicaFailure")
    if replica_failure and replica_failure.status == "True":
        issues.append(f"ReplicaFailure: {replica_failure.message or replica_failure.reason}")

    if updated < desired and not (progressing and progressing.status == "False"):
        issues.append(f"Rollout in progress: {updated} of {desired} replicas updated")

    if status.get("observedGeneration", 0) < meta.get("generation", 0):
        issues.append("Latest spec change not yet picked up by the controller")

    if not issues:
        return None

    return DeploymentIssue(
        name=meta.get("name", "?"),
        namespace=meta.get("namespace", "default"),
        desired=desired,
        ready=ready,
        available=available,
        unavailable=unavailable,
        updated=updated,
        issues=issues,
        conditions=conditions,
    )


def inspect_deployments() -> DeploymentsReport:
    deployments = get_json(["get", "deployments", "-A"]).get("items", [])
    unhealthy = [d for d in (_inspect_deployment(dep) for dep in deployments) if d is not None]
    logger.info("Deployment inspector: {} deployments, {} unhealthy", len(deployments), len(unhealthy))
    return DeploymentsReport(
        healthy=not unhealthy,
        total_deployments=len(deployments),
        unhealthy_deployments=unhealthy,
    )
