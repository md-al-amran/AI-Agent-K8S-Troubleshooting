"""Run kubectl safely and return structured results.

Only read-only verbs are allowed, commands are passed as an argument list
(never through a shell), and every call has a timeout.
"""

import json
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from loguru import logger
from pydantic import BaseModel

from app.core.config import get_settings

# kubectl verbs this agent is allowed to run. Everything here only reads.
ALLOWED_VERBS = {"get", "describe", "logs", "version", "cluster-info", "config"}
# `kubectl config` can also change the kubeconfig, so only these read-only subcommands are allowed.
ALLOWED_CONFIG_SUBCOMMANDS = {"view", "current-context"}

# Which cluster the current request talks to, e.g. ["--context", "kind-demo"].
# Set once per investigation with `use_cluster(...)`, so the inspectors don't need to know about it.
_cluster_args: ContextVar[list[str]] = ContextVar("cluster_args", default=[])

# Keep stderr short in logs and API responses.
MAX_ERROR_CHARS = 1000


class KubectlError(Exception):
    """Raised when kubectl cannot be run at all or the cluster is unreachable.

    `hints` are beginner-friendly things to check, shown in the UI.
    """

    def __init__(self, message: str, hints: list[str] | None = None) -> None:
        super().__init__(message)
        self.hints = hints or []


@contextmanager
def use_cluster(cluster_args: list[str]) -> Iterator[None]:
    """Run every kubectl call inside this block against the given cluster."""
    token = _cluster_args.set(cluster_args)
    try:
        yield
    finally:
        _cluster_args.reset(token)


class KubectlResult(BaseModel):
    command: str
    success: bool
    return_code: int
    stdout: str
    stderr: str
    duration_ms: int

    def parse_json(self) -> Any:
        """Parse stdout as JSON (for commands run with `-o json`)."""
        return json.loads(self.stdout)


def _build_command(args: list[str], cluster_args: list[str]) -> list[str]:
    settings = get_settings()
    command = [settings.kubectl_binary]
    if settings.kubeconfig_path:
        command += ["--kubeconfig", settings.kubeconfig_path]
    if args[0] != "config":  # config commands read the kubeconfig itself, not a cluster
        # Default timeout first, so a --request-timeout inside cluster_args wins (kubectl uses the last one).
        command += [f"--request-timeout={settings.kubectl_timeout_seconds}s", *cluster_args]
    return command + args


def _check_allowed(args: list[str]) -> None:
    if not args or args[0] not in ALLOWED_VERBS:
        raise ValueError(f"kubectl verb not allowed: {args[:1]}")
    if args[0] == "config" and (len(args) < 2 or args[1] not in ALLOWED_CONFIG_SUBCOMMANDS):
        raise ValueError(f"kubectl config subcommand not allowed: {args[1:2]}")
    if args[0] == "config" and any(a.split("=")[0] in ("--raw", "--flatten") for a in args):
        raise ValueError("kubectl config --raw/--flatten would expose credentials")


def run_kubectl(args: list[str], timeout: int | None = None, cluster_args: list[str] | None = None) -> KubectlResult:
    """Run `kubectl <args>` and return its output. Never raises for a non-zero exit.

    Example: run_kubectl(["get", "pods", "-A", "-o", "json"])
    `cluster_args` overrides the cluster chosen with `use_cluster` (used when
    checking several clusters in parallel threads).
    """
    _check_allowed(args)

    settings = get_settings()
    timeout = timeout or settings.kubectl_timeout_seconds + 5
    command = _build_command(args, cluster_args if cluster_args is not None else _cluster_args.get())
    display = "kubectl " + " ".join(args)
    started = time.monotonic()

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return_code = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr.strip()[:MAX_ERROR_CHARS]
    except FileNotFoundError as exc:
        raise KubectlError(
            "kubectl is not installed on the backend.",
            [
                "Install kubectl: https://kubernetes.io/docs/tasks/tools/",
                f"Or set KUBECTL_BINARY in backend/.env (currently '{settings.kubectl_binary}')",
            ],
        ) from exc
    except subprocess.TimeoutExpired:
        return_code, stdout, stderr = -1, "", f"Timed out after {timeout}s"

    duration_ms = int((time.monotonic() - started) * 1000)
    result = KubectlResult(
        command=display,
        success=return_code == 0,
        return_code=return_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
    )

    if result.success:
        logger.debug("{} ok in {}ms", display, duration_ms)
    else:
        logger.warning("{} failed (code {}) in {}ms: {}", display, return_code, duration_ms, stderr)
    return result


def get_json(args: list[str]) -> dict[str, Any]:
    """Run a kubectl `get` with `-o json` and return the parsed object.

    Raises KubectlError if the command fails, because callers cannot continue
    without the data.
    """
    result = run_kubectl([*args, "-o", "json"])
    if not result.success:
        raise KubectlError(f"{result.command} failed: {result.stderr or 'unknown error'}")
    try:
        return result.parse_json()
    except json.JSONDecodeError as exc:
        raise KubectlError(f"{result.command} returned invalid JSON") from exc


def check_cluster_access(cluster_name: str = "the cluster") -> None:
    """Fail fast with a clear, beginner-friendly message if kubectl cannot reach the cluster."""
    from app.kubernetes.errors import explain_kubectl_error

    result = run_kubectl(["get", "--raw", "/readyz"])
    if not result.success:
        message, hints = explain_kubectl_error(result.stderr, cluster_name)
        raise KubectlError(message, hints)
