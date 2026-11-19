"""Logs Collector: read recent logs from failing containers and keep only useful lines.

Source: kubectl logs <pod> -n <namespace> -c <container> --tail=N [--previous]
"""

import re

from loguru import logger

from app.core.config import get_settings
from app.kubernetes.executor import run_kubectl
from app.kubernetes.utils import shorten
from app.models.investigation import ContainerIssue, ContainerLogs, LogFinding, LogsReport, ProblemPod

# Checked in order; a line gets the first category that matches.
LOG_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "exception",
        re.compile(r"exception|traceback|panic:|unhandled|segmentation fault|stack ?trace", re.I),
    ),
    (
        "connection",
        re.compile(
            r"connection (refused|reset|timed out)|econnrefused|could not connect|unable to connect"
            r"|no route to host|dial tcp|i/o timeout|no such host|name or service not known"
            r"|temporary failure in name resolution|getaddrinfo",
            re.I,
        ),
    ),
    (
        "image",
        re.compile(
            r"exec format error|executable file not found|exec .*: (not found|invalid argument|no such file or directory|permission denied)"
            r"|manifest unknown",
            re.I,
        ),
    ),
    (
        "config",
        re.compile(
            r"(environment|env) (variable|var)|is not set|must be set|missing required|keyerror"
            r"|no such file or directory|permission denied|invalid (config|configuration)",
            re.I,
        ),
    ),
    (
        "startup",
        re.compile(
            r"failed to start|cannot start|address already in use|out of memory|oom|killed"
            r"|exit(ed)? (with )?(code|status)",
            re.I,
        ),
    ),
    ("error", re.compile(r"\b(error|fatal|failed|failure|critical)\b", re.I)),
]

# Container states where the process never ran, so there are no logs to read.
NO_LOG_REASONS = {
    "ImagePullBackOff",
    "ErrImagePull",
    "InvalidImageName",
    "CreateContainerConfigError",
    "CreateContainerError",
    "ContainerCreating",
    "PodInitializing",
}

TAIL_CONTEXT_LINES = 5

# kubectl sometimes prints these to stdout with exit code 0 when logs are gone.
UNAVAILABLE_MARKERS = ("unable to retrieve container logs", "previous terminated container")


def _categorize(line: str) -> str | None:
    for category, pattern in LOG_PATTERNS:
        if pattern.search(line):
            return category
    return None


def _extract(text: str, max_findings: int) -> tuple[list[LogFinding], list[str]]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    findings: list[LogFinding] = []
    seen: set[str] = set()

    for line in lines:
        category = _categorize(line)
        if not category:
            continue
        short = shorten(line) or ""
        if short in seen:  # the same error repeated many times only needs to appear once
            continue
        seen.add(short)
        findings.append(LogFinding(category=category, line=short))

    # Keep the most recent findings, since they are closest to the crash.
    findings = findings[-max_findings:]
    tail = [shorten(line) or "" for line in lines[-TAIL_CONTEXT_LINES:]]
    return findings, tail


def _read_logs(pod: ProblemPod, container: ContainerIssue) -> ContainerLogs:
    settings = get_settings()
    base = ["logs", pod.name, "-n", pod.namespace, "-c", container.name, f"--tail={settings.log_tail_lines}"]

    # Which run holds the crash output:
    # - terminated now (between restarts): the current container
    # - waiting in CrashLoopBackOff: the previous container
    if container.state == "waiting" and container.restarts > 0:
        attempts = [True, False]
    elif container.restarts > 0:
        attempts = [False, True]
    else:
        attempts = [False]

    error = None
    for previous in attempts:
        result = run_kubectl(base + (["--previous"] if previous else []))
        output = result.stdout.strip()
        if result.success and output and not output.lower().startswith(UNAVAILABLE_MARKERS):
            findings, tail = _extract(result.stdout, settings.max_log_lines_per_container)
            return ContainerLogs(
                pod=pod.name,
                namespace=pod.namespace,
                container=container.name,
                previous=previous,
                findings=findings,
                tail=tail,
            )
        error = result.stderr or output or "No log output"

    return ContainerLogs(
        pod=pod.name,
        namespace=pod.namespace,
        container=container.name,
        error=shorten(error),
    )


def collect_logs(problematic_pods: list[ProblemPod]) -> LogsReport:
    """Collect a short, filtered set of log lines for each failing container."""
    settings = get_settings()
    report = LogsReport()

    for index, pod in enumerate(problematic_pods):
        pod_ref = f"{pod.namespace}/{pod.name}"
        if index >= settings.max_pods_for_logs:
            report.skipped.append(f"{pod_ref}: over the limit of {settings.max_pods_for_logs} pods")
            continue
        if pod.node is None:
            report.skipped.append(f"{pod_ref}: not scheduled to a node, so it has no logs")
            continue

        for container in pod.containers:
            never_ran = container.state == "waiting" and container.reason in NO_LOG_REASONS
            if never_ran and container.restarts == 0:
                report.skipped.append(f"{pod_ref}/{container.name}: {container.reason}, container never started")
                continue
            report.containers.append(_read_logs(pod, container))

    logger.info("Logs collector: read {} containers, skipped {}", len(report.containers), len(report.skipped))
    return report
