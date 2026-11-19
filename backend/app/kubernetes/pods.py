"""Pod Inspector: find pods that are not healthy and say why.

Source: kubectl get pods -A -o json
"""

from typing import Any

from loguru import logger

from app.core.config import get_settings
from app.kubernetes.executor import get_json
from app.kubernetes.utils import minutes_since, shorten
from app.models.investigation import ContainerIssue, PodReport, ProblemPod

# Waiting reasons that always mean the container is broken.
BROKEN_WAITING_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "InvalidImageName",
    "CreateContainerConfigError",
    "CreateContainerError",
    "RunContainerError",
}

# Waiting reasons that are normal for a short time, but a problem if they last.
SLOW_WAITING_REASONS = {"ContainerCreating", "PodInitializing"}

# A running container that has not passed its readiness probe for this long is a problem.
NOT_READY_AFTER_MINUTES = 1

# Restarts with a failed exit before a pod counts as crash looping.
CRASH_LOOP_RESTARTS = 3

# Used to pick the main status when a pod has several problems.
PRIORITY = [
    "OOMKilled",
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "InvalidImageName",
    "CreateContainerConfigError",
    "CreateContainerError",
    "RunContainerError",
    "Error",
    "Evicted",
    "Failed",
    "Pending",
    "ContainerCreating (stuck)",
    "Terminating (stuck)",
    "NotReady",
    "Unknown",
]


def fetch_pods() -> list[dict[str, Any]]:
    """Return the raw pod objects for every namespace."""
    return get_json(["get", "pods", "-A"]).get("items", [])


def _container_issue(status: dict[str, Any], init_container: bool) -> ContainerIssue:
    state_obj = status.get("state") or {}
    state = next(iter(state_obj), "unknown")
    details = state_obj.get(state) or {}
    last = (status.get("lastState") or {}).get("terminated") or {}
    return ContainerIssue(
        name=status.get("name", "?"),
        init_container=init_container,
        state=state,
        reason=details.get("reason"),
        message=shorten(details.get("message")),
        exit_code=details.get("exitCode"),
        ready=bool(status.get("ready")),
        restarts=status.get("restartCount", 0),
        last_termination_reason=last.get("reason"),
        last_exit_code=last.get("exitCode"),
        state_minutes=minutes_since(details.get("startedAt")),
    )


def _container_problems(container: ContainerIssue, pod_age: int | None, stuck_after: int) -> list[str]:
    problems: list[str] = []

    if container.state == "waiting" and container.reason in BROKEN_WAITING_REASONS:
        problems.append(container.reason)
    if container.state == "waiting" and container.reason in SLOW_WAITING_REASONS:
        if pod_age is not None and pod_age >= stuck_after:
            problems.append("ContainerCreating (stuck)")

    if container.reason == "OOMKilled" or container.last_termination_reason == "OOMKilled":
        problems.append("OOMKilled")

    # A finished container is only a problem if it failed. Init containers
    # that exit 0 are expected.
    if container.state == "terminated" and container.exit_code not in (0, None):
        problems.append("Error")

    # Between restarts a crashing container shows "Error", not CrashLoopBackOff.
    # Repeated failed exits mean it is crash looping either way.
    failed_last_run = container.last_exit_code not in (0, None) or container.exit_code not in (0, None)
    if container.restarts >= CRASH_LOOP_RESTARTS and failed_last_run and "CrashLoopBackOff" not in problems:
        problems.append("CrashLoopBackOff")

    # Running but failing its readiness probe for over a minute (apps here start in seconds).
    if container.state == "running" and not container.ready and not container.init_container:
        running_for = container.state_minutes if container.state_minutes is not None else pod_age
        if running_for is not None and running_for >= NOT_READY_AFTER_MINUTES:
            problems.append("NotReady")

    return problems


def _inspect_pod(pod: dict[str, Any], stuck_after: int) -> ProblemPod | None:
    meta = pod.get("metadata", {})
    spec = pod.get("spec", {})
    status = pod.get("status", {})
    phase = status.get("phase")
    age = minutes_since(meta.get("creationTimestamp"))

    # Completed pods (for example finished Jobs) are fine.
    if phase == "Succeeded":
        return None

    containers = [_container_issue(s, True) for s in status.get("initContainerStatuses", [])]
    containers += [_container_issue(s, False) for s in status.get("containerStatuses", [])]

    problems: list[str] = []
    message = status.get("message")

    if phase == "Pending":
        problems.append("Pending")
        unscheduled = next(
            (c for c in status.get("conditions", []) if c.get("type") == "PodScheduled" and c.get("status") == "False"),
            None,
        )
        if unscheduled:
            message = message or unscheduled.get("message")
    elif phase == "Failed":
        problems.append(status.get("reason") or "Failed")  # e.g. Evicted
    elif phase == "Unknown":
        problems.append("Unknown")

    deleting_for = minutes_since(meta.get("deletionTimestamp"))
    if deleting_for is not None and deleting_for >= stuck_after:
        problems.append("Terminating (stuck)")

    problem_containers = []
    for container in containers:
        container_problems = _container_problems(container, age, stuck_after)
        if container_problems:
            problems.extend(container_problems)
            problem_containers.append(container)

    if not problems:
        return None

    # A pod that is Pending only because its containers are still pulling
    # images (not stuck yet) is just starting up.
    if problems == ["Pending"] and age is not None and age < stuck_after and not message:
        return None

    unique = list(dict.fromkeys(problems))
    main = min(unique, key=lambda p: PRIORITY.index(p) if p in PRIORITY else len(PRIORITY))
    owners = meta.get("ownerReferences") or []
    regular = [c for c in containers if not c.init_container]

    return ProblemPod(
        name=meta.get("name", "?"),
        namespace=meta.get("namespace", "default"),
        status=main,
        reasons=unique,
        phase=phase,
        message=shorten(message),
        node=spec.get("nodeName"),
        owner=f"{owners[0].get('kind')}/{owners[0].get('name')}" if owners else None,
        ready=f"{sum(c.ready for c in regular)}/{len(spec.get('containers', []))}",
        restarts=sum(c.restarts for c in containers),
        age_minutes=age,
        containers=problem_containers or containers,
    )


def inspect_pods(pods: list[dict[str, Any]]) -> PodReport:
    """Check every pod and return the unhealthy ones."""
    stuck_after = get_settings().stuck_container_creating_minutes
    problematic = [p for p in (_inspect_pod(pod, stuck_after) for pod in pods) if p is not None]
    logger.info("Pod inspector: {} pods, {} problematic", len(pods), len(problematic))
    return PodReport(
        healthy=not problematic,
        total_pods=len(pods),
        problematic_pods=problematic,
    )
