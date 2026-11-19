"""Clusters: list the contexts in the kubeconfig and say how to reach each one.

Source: kubectl config view -o json   (credentials are redacted by kubectl)
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from loguru import logger
from pydantic import BaseModel

from app.core.config import get_settings
from app.kubernetes.errors import explain_kubectl_error
from app.kubernetes.executor import KubectlError, run_kubectl

LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}
REACHABILITY_TIMEOUT_SECONDS = 5


class UnknownClusterError(KubectlError):
    """The requested context is not in the kubeconfig (a bad request, not a server problem)."""


class ClusterInfo(BaseModel):
    name: str  # the kubeconfig context name; this is what the user picks
    cluster: str
    server: str
    namespace: str | None = None
    current: bool = False  # the kubeconfig's current-context
    reachable: bool | None = None  # None = not checked
    error: str | None = None


def _read_kubeconfig() -> dict:
    result = run_kubectl(["config", "view", "-o", "json"])
    if not result.success:
        message, hints = explain_kubectl_error(result.stderr, "your kubeconfig")
        raise KubectlError(message, hints)
    return result.parse_json()


def _no_clusters_error() -> KubectlError:
    path = get_settings().kubeconfig_path or "~/.kube/config (or $KUBECONFIG)"
    return KubectlError(
        "No Kubernetes clusters found in your kubeconfig.",
        [
            f"The backend reads: {path}. Check that the file exists (KUBECONFIG_PATH in backend/.env)",
            "With Docker, your ~/.kube folder is mounted into the backend container. Make sure it exists",
            "Run `kubectl config get-contexts` on your machine to see your clusters",
        ],
    )


def list_clusters() -> list[ClusterInfo]:
    """Every context in the kubeconfig, current one first. Raises KubectlError if there are none."""
    config = _read_kubeconfig()
    servers = {c["name"]: (c.get("cluster") or {}).get("server", "") for c in config.get("clusters") or []}
    current = config.get("current-context") or ""

    clusters = []
    for context in config.get("contexts") or []:
        details = context.get("context") or {}
        cluster_name = details.get("cluster", "")
        clusters.append(
            ClusterInfo(
                name=context["name"],
                cluster=cluster_name,
                server=servers.get(cluster_name, ""),
                namespace=details.get("namespace"),
                current=context["name"] == current,
            )
        )
    if not clusters:
        raise _no_clusters_error()
    clusters.sort(key=lambda c: (not c.current, c.name))
    return clusters


def find_cluster(name: str | None) -> ClusterInfo:
    """The context with this name, or the current context when name is empty."""
    clusters = list_clusters()
    if not name:
        return next((c for c in clusters if c.current), clusters[0])
    for cluster in clusters:
        if cluster.name == name:
            return cluster
    raise UnknownClusterError(
        f"Cluster '{name}' is not in your kubeconfig.",
        ["Refresh the cluster list in the dashboard", "Run `kubectl config get-contexts` to see the available clusters"],
    )


def cluster_args(cluster: ClusterInfo) -> list[str]:
    """kubectl flags that point at this cluster.

    kind clusters listen on 127.0.0.1, which a Docker container cannot reach.
    When KIND_INTERNAL_NETWORK is on (docker-compose.kind.yml), use the kind
    node's name on the shared `kind` Docker network instead. The cluster's
    certificate is valid for that name, so TLS still verifies.
    """
    args = ["--context", cluster.name]
    host = urlparse(cluster.server).hostname or ""
    if get_settings().kind_internal_network and cluster.cluster.startswith("kind-") and host in LOCAL_HOSTS:
        kind_name = cluster.cluster.removeprefix("kind-")
        args.append(f"--server=https://{kind_name}-control-plane:6443")
    return args


def _check(cluster: ClusterInfo) -> ClusterInfo:
    result = run_kubectl(
        ["get", "--raw", "/readyz"],
        timeout=REACHABILITY_TIMEOUT_SECONDS + 2,
        cluster_args=[*cluster_args(cluster), f"--request-timeout={REACHABILITY_TIMEOUT_SECONDS}s"],
    )
    if result.success:
        return cluster.model_copy(update={"reachable": True})
    message, _ = explain_kubectl_error(result.stderr, cluster.name)
    return cluster.model_copy(update={"reachable": False, "error": message})


def list_clusters_with_status() -> list[ClusterInfo]:
    """All clusters, each checked in parallel (a dead cluster takes a few seconds to time out)."""
    clusters = list_clusters()
    with ThreadPoolExecutor(max_workers=min(8, len(clusters))) as pool:
        checked = list(pool.map(_check, clusters))
    logger.info("Clusters: {}", ", ".join(f"{c.name}={'up' if c.reachable else 'down'}" for c in checked))
    return checked
