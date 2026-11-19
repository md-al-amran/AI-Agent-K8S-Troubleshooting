"""Turn raw kubectl errors into short, beginner-friendly messages with things to check."""

import re

# (pattern in kubectl stderr, message, hints). The first match wins.
_RULES: list[tuple[re.Pattern[str], str, list[str]]] = [
    (
        re.compile(r"no configuration has been provided|kubeconfig.*(no such file|not found)|stat .*config.*no such file", re.I),
        "No kubeconfig file was found.",
        [
            "Check KUBECONFIG_PATH in backend/.env (empty means ~/.kube/config)",
            "With Docker, make sure your ~/.kube folder exists (it is mounted into the backend container)",
            "Run `kubectl config get-contexts` on your machine to confirm you have clusters configured",
        ],
    ),
    (
        re.compile(r"context .* (does not exist|not found)|no context exists", re.I),
        "That cluster is not in your kubeconfig.",
        [
            "Run `kubectl config get-contexts` to see the available clusters",
            "Refresh the cluster list in the dashboard",
        ],
    ),
    (
        re.compile(r"unauthorized|must be logged in|provide credentials|token.*expired|certificate.*expired", re.I),
        "The cluster rejected your credentials.",
        [
            "Your kubeconfig credentials may have expired. Download them again (for example `az aks get-credentials`, `kind export kubeconfig`)",
            "Check that `kubectl get pods -A` works on your machine with this cluster",
        ],
    ),
    (
        re.compile(r"forbidden", re.I),
        "Your kubeconfig user is not allowed to read this cluster.",
        [
            "The agent needs read access (get/list) to pods, pods/log, events, deployments, services and endpointslices in all namespaces",
            "Ask a cluster admin for a read-only role such as the built-in `view` ClusterRole",
        ],
    ),
    (
        re.compile(r"x509|certificate signed by unknown authority|tls:", re.I),
        "The cluster's TLS certificate could not be verified.",
        [
            "The kubeconfig may belong to an older version of this cluster. Download the credentials again",
            "If the backend runs in Docker against kind, start it with docker-compose.kind.yml",
        ],
    ),
    (
        re.compile(
            r"unable to connect|connection refused|no such host|dial tcp|i/o timeout|timed out"
            r"|no route to host|network is unreachable|eof|connection reset",
            re.I,
        ),
        "Unable to connect to the Kubernetes cluster.",
        [
            "Is the cluster running? (kind: `docker ps`; cloud clusters: check it is started in the cloud console)",
            "Check the server address in your kubeconfig and that this machine can reach it (VPN, firewall)",
            "If the backend runs in Docker and the cluster is local (kind), use docker-compose.kind.yml",
        ],
    ),
]

_DEFAULT_HINTS = [
    "Check the kubeconfig path and that the cluster is reachable",
    "Check that your kubeconfig user can read pods, events, deployments and services",
    "Run `kubectl get pods -A` on your machine to see the full error",
]


def explain_kubectl_error(stderr: str, cluster_name: str = "the cluster") -> tuple[str, list[str]]:
    """Return (message, hints) for a failed kubectl command."""
    for pattern, message, hints in _RULES:
        if pattern.search(stderr or ""):
            return f"{message} ({cluster_name})", hints
    return f"kubectl could not talk to {cluster_name}.", _DEFAULT_HINTS
