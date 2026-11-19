"""Shapes of the evidence returned by POST /investigate.

Every report has an `error` field. If one step fails (for example missing
RBAC permission to list events), that report carries the error and the other
steps still run.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.diagnosis import Diagnosis

# ---------- Pods ----------


class ContainerIssue(BaseModel):
    name: str
    init_container: bool = False
    state: str  # waiting | running | terminated | unknown
    reason: str | None = None
    message: str | None = None
    exit_code: int | None = None
    ready: bool = False
    restarts: int = 0
    last_termination_reason: str | None = None
    last_exit_code: int | None = None
    state_minutes: int | None = None  # how long the container has been in its current state


class ProblemPod(BaseModel):
    name: str
    namespace: str
    status: str  # the main problem, e.g. CrashLoopBackOff
    reasons: list[str] = Field(default_factory=list)  # every problem found, e.g. CrashLoopBackOff + OOMKilled
    phase: str | None = None
    message: str | None = None
    node: str | None = None
    owner: str | None = None  # e.g. ReplicaSet/payment-service-5d9f
    ready: str = "0/0"
    restarts: int = 0
    age_minutes: int | None = None
    containers: list[ContainerIssue] = Field(default_factory=list)


class PodReport(BaseModel):
    healthy: bool = True
    total_pods: int = 0
    problematic_pods: list[ProblemPod] = Field(default_factory=list)
    error: str | None = None


# ---------- Logs ----------


class LogFinding(BaseModel):
    category: str  # exception | connection | config | image | startup | error
    line: str


class ContainerLogs(BaseModel):
    pod: str
    namespace: str
    container: str
    previous: bool = False  # true when logs come from the last crashed run
    findings: list[LogFinding] = Field(default_factory=list)
    tail: list[str] = Field(default_factory=list)  # last few lines, for context
    error: str | None = None


class LogsReport(BaseModel):
    containers: list[ContainerLogs] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)  # pods with no logs to read, and why
    error: str | None = None


# ---------- Events ----------


class EventFinding(BaseModel):
    namespace: str
    object: str  # e.g. Pod/payment-service-5d9f-abcde
    reason: str
    category: str | None = None  # e.g. FailedScheduling, FailedPull
    type: str
    message: str
    count: int = 1
    last_seen: datetime | None = None
    age_minutes: int | None = None  # minutes since last_seen, so old events are easy to spot


class EventsReport(BaseModel):
    total_warnings: int = 0
    # Events about things that have since recovered (pod now healthy or gone, node Ready again).
    # They are dropped from `findings` so old startup noise is not reported as a live problem.
    resolved_ignored: int = 0
    counts_by_category: dict[str, int] = Field(default_factory=dict)
    findings: list[EventFinding] = Field(default_factory=list)
    error: str | None = None


# ---------- Deployments ----------


class DeploymentCondition(BaseModel):
    type: str
    status: str
    reason: str | None = None
    message: str | None = None


class DeploymentIssue(BaseModel):
    name: str
    namespace: str
    desired: int = 0
    ready: int = 0
    available: int = 0
    unavailable: int = 0
    updated: int = 0
    issues: list[str] = Field(default_factory=list)
    conditions: list[DeploymentCondition] = Field(default_factory=list)


class DeploymentsReport(BaseModel):
    healthy: bool = True
    total_deployments: int = 0
    unhealthy_deployments: list[DeploymentIssue] = Field(default_factory=list)
    error: str | None = None


# ---------- Network ----------


class ServiceIssue(BaseModel):
    name: str
    namespace: str
    type: str  # SelectorMismatch | NoReadyEndpoints | TargetPortMismatch
    message: str
    selector: dict[str, str] = Field(default_factory=dict)


class DNSStatus(BaseModel):
    healthy: bool = True
    coredns_pods_ready: str = "0/0"
    dns_service_found: bool = False
    dns_ready_endpoints: int = 0
    issues: list[str] = Field(default_factory=list)


class NetworkReport(BaseModel):
    healthy: bool = True
    total_services: int = 0
    service_issues: list[ServiceIssue] = Field(default_factory=list)
    dns: DNSStatus = Field(default_factory=DNSStatus)
    error: str | None = None


# ---------- Whole investigation ----------


class InvestigationSummary(BaseModel):
    healthy: bool
    problematic_pods: int
    warning_events: int
    unhealthy_deployments: int
    network_issues: int
    failed_steps: list[str] = Field(default_factory=list)


class Investigation(BaseModel):
    started_at: datetime
    duration_ms: int
    summary: InvestigationSummary
    pods: PodReport
    logs: LogsReport
    events: EventsReport
    deployments: DeploymentsReport
    network: NetworkReport


class InvestigateResponse(BaseModel):
    # success: evidence and diagnosis
    # partial: evidence collected, but the AI diagnosis failed (see `error`)
    # error:   the cluster could not be investigated (see `error`)
    status: Literal["success", "partial", "error"]
    diagnosis: Diagnosis | None = None
    investigation: Investigation | None = None
    error: str | None = None
    investigation_id: str | None = None  # history row in InsForge (None when auth is off)
    cluster: str | None = None  # kubeconfig context that was investigated
    hints: list[str] = Field(default_factory=list)  # beginner-friendly things to check when something failed


class InvestigateRequest(BaseModel):
    # kubeconfig context to investigate. Empty = the kubeconfig's current context.
    cluster: str | None = None

