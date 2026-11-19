"""Network Inspector: check that services reach pods and that cluster DNS works.

Sources:
  kubectl get services -A -o json
  kubectl get endpointslices -A -o json
  pods from the Pod Inspector (to compare service selectors with pod labels)
"""

from collections import defaultdict
from typing import Any

from loguru import logger

from app.kubernetes.executor import get_json
from app.models.investigation import DNSStatus, NetworkReport, ServiceIssue

DNS_NAMESPACE = "kube-system"
DNS_SERVICE = "kube-dns"
DNS_POD_LABEL = ("k8s-app", "kube-dns")
SERVICE_NAME_LABEL = "kubernetes.io/service-name"


def _ready_endpoints_by_service(slices: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    """Count ready endpoint addresses per (namespace, service)."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for endpoint_slice in slices:
        meta = endpoint_slice.get("metadata", {})
        service = (meta.get("labels") or {}).get(SERVICE_NAME_LABEL)
        if not service:
            continue
        for endpoint in endpoint_slice.get("endpoints") or []:
            # A missing "ready" condition means ready.
            if (endpoint.get("conditions") or {}).get("ready", True):
                counts[(meta.get("namespace", ""), service)] += len(endpoint.get("addresses") or [])
    return counts


def _matches(labels: dict[str, str], selector: dict[str, str]) -> bool:
    return all(labels.get(key) == value for key, value in selector.items())


def _active_pods_by_namespace(pods: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_namespace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pod in pods:
        if pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
            continue
        by_namespace[pod.get("metadata", {}).get("namespace", "")].append(pod)
    return by_namespace


def _near_misses(selector: dict[str, str], pods: list[dict[str, Any]]) -> list[str]:
    """Label values that pods actually use for the selector keys, e.g. 'app=payment-v2'.

    Helps spot a typo or a renamed label behind a selector mismatch.
    """
    found: set[str] = set()
    for pod in pods:
        labels = pod.get("metadata", {}).get("labels") or {}
        for key in selector:
            if key in labels and labels[key] != selector[key]:
                found.add(f"{key}={labels[key]}")
    return sorted(found)[:5]


def _declared_ports(pods: list[dict[str, Any]]) -> tuple[set[int], set[str]]:
    numbers: set[int] = set()
    names: set[str] = set()
    for pod in pods:
        for container in pod.get("spec", {}).get("containers", []):
            for port in container.get("ports") or []:
                numbers.add(port.get("containerPort"))
                if port.get("name"):
                    names.add(port["name"])
    return numbers, names


def _check_service(
    service: dict[str, Any],
    namespace_pods: list[dict[str, Any]],
    ready_endpoints: int,
) -> list[ServiceIssue]:
    meta = service.get("metadata", {})
    spec = service.get("spec", {})
    selector = spec.get("selector") or {}
    name, namespace = meta.get("name", "?"), meta.get("namespace", "default")

    def issue(kind: str, message: str) -> ServiceIssue:
        return ServiceIssue(name=name, namespace=namespace, type=kind, message=message, selector=selector)

    # ExternalName services and services without a selector manage endpoints by hand.
    if spec.get("type") == "ExternalName" or not selector:
        return []

    selector_text = ",".join(f"{k}={v}" for k, v in selector.items())
    matching = [p for p in namespace_pods if _matches(p.get("metadata", {}).get("labels") or {}, selector)]

    if not matching:
        hint = _near_misses(selector, namespace_pods)
        message = f"No pods match selector {selector_text}"
        if hint:
            message += f". Pods in this namespace use: {', '.join(hint)}"
        return [issue("SelectorMismatch", message)]

    issues: list[ServiceIssue] = []
    if ready_endpoints == 0:
        issues.append(
            issue("NoReadyEndpoints", f"{len(matching)} pod(s) match {selector_text} but none are ready to receive traffic")
        )

    # Only compare ports when the pods declare them (declaring is optional).
    numbers, names = _declared_ports(matching)
    if numbers:
        for port in spec.get("ports") or []:
            target = port.get("targetPort", port.get("port"))
            missing = (isinstance(target, int) and target not in numbers) or (
                isinstance(target, str) and target not in names
            )
            if missing:
                issues.append(
                    issue(
                        "TargetPortMismatch",
                        f"Service port {port.get('port')} targets {target}, "
                        f"but matching pods expose {sorted(numbers)}",
                    )
                )
    return issues


def _check_dns(services: list[dict[str, Any]], pods: list[dict[str, Any]], ready_endpoints: dict) -> DNSStatus:
    key, value = DNS_POD_LABEL
    dns_pods = [
        p
        for p in pods
        if p.get("metadata", {}).get("namespace") == DNS_NAMESPACE
        and (p.get("metadata", {}).get("labels") or {}).get(key) == value
    ]
    ready = sum(
        1
        for p in dns_pods
        if any(c.get("type") == "Ready" and c.get("status") == "True" for c in p.get("status", {}).get("conditions", []))
    )
    service_found = any(
        s.get("metadata", {}).get("namespace") == DNS_NAMESPACE and s.get("metadata", {}).get("name") == DNS_SERVICE
        for s in services
    )
    endpoints = ready_endpoints.get((DNS_NAMESPACE, DNS_SERVICE), 0)

    issues: list[str] = []
    if not dns_pods:
        issues.append(f"No DNS pods found in {DNS_NAMESPACE} with label {key}={value}")
    elif ready == 0:
        issues.append("No DNS pods are ready, so service names will not resolve")
    elif ready < len(dns_pods):
        issues.append(f"Only {ready} of {len(dns_pods)} DNS pods are ready")
    if not service_found:
        issues.append(f"Service {DNS_NAMESPACE}/{DNS_SERVICE} not found")
    elif endpoints == 0:
        issues.append(f"Service {DNS_NAMESPACE}/{DNS_SERVICE} has no ready endpoints")

    return DNSStatus(
        # One unready replica out of several still answers queries, so that alone is not unhealthy.
        healthy=bool(dns_pods) and ready > 0 and service_found and endpoints > 0,
        coredns_pods_ready=f"{ready}/{len(dns_pods)}",
        dns_service_found=service_found,
        dns_ready_endpoints=endpoints,
        issues=issues,
    )


def inspect_network(pods: list[dict[str, Any]] | None) -> NetworkReport:
    """Check services, their endpoints, and cluster DNS.

    `pods` comes from the Pod Inspector. If it is None (pods could not be
    listed), the checks that need pod labels are skipped.
    """
    services = get_json(["get", "services", "-A"]).get("items", [])
    slices = get_json(["get", "endpointslices", "-A"]).get("items", [])
    ready_endpoints = _ready_endpoints_by_service(slices)

    report = NetworkReport(total_services=len(services))
    if pods is None:
        report.error = "Pods could not be listed, so selector and DNS checks were skipped"
        return report

    pods_by_namespace = _active_pods_by_namespace(pods)
    for service in services:
        meta = service.get("metadata", {})
        namespace = meta.get("namespace", "")
        report.service_issues += _check_service(
            service,
            pods_by_namespace.get(namespace, []),
            ready_endpoints.get((namespace, meta.get("name", "")), 0),
        )

    report.dns = _check_dns(services, pods, ready_endpoints)
    report.healthy = not report.service_issues and report.dns.healthy
    logger.info(
        "Network inspector: {} services, {} issues, DNS healthy={}",
        len(services),
        len(report.service_issues),
        report.dns.healthy,
    )
    return report
