"""Failure lab: run the agent against one cluster and record what it found about one namespace.

This is exactly what POST /investigate does (same investigation + AI diagnosis),
plus a filter on the test namespace so results are easy to grade.

  python -m scripts.failure_lab --cluster kind-ecommerce-cluster-01 --namespace ecommerce --label F1-diagnose

Writes docs/failure-lab/results/<label>.json and prints a short summary.
Read-only: it never changes the cluster.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.ai.llm_client import LLMError
from app.ai.reasoner import diagnose
from app.kubernetes.clusters import cluster_args, find_cluster
from app.kubernetes.executor import KubectlError, use_cluster
from app.services.investigation import investigate_cluster

RESULTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "failure-lab" / "results"


def _in_namespace(resource: str, namespace: str) -> bool:
    parts = resource.split("/")
    return len(parts) == 3 and parts[1] == namespace or resource.startswith(f"{namespace}/")


def run(cluster_name: str, namespace: str, label: str) -> dict:
    cluster = find_cluster(cluster_name)
    record: dict = {
        "label": label,
        "cluster": cluster.name,
        "namespace": namespace,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        with use_cluster(cluster_args(cluster)):
            inv = investigate_cluster(cluster_name=cluster.name)
    except KubectlError as exc:
        record["error"] = str(exc)
        return record

    pods = [p for p in inv.pods.problematic_pods if p.namespace == namespace]
    record["kubernetes_status"] = [
        {"pod": p.name, "status": p.status, "reasons": p.reasons, "ready": p.ready, "restarts": p.restarts,
         "message": p.message}
        for p in pods
    ]
    record["evidence"] = {
        "logs": [
            {"pod": c.pod, "container": c.container, "previous": c.previous,
             "findings": [f"[{f.category}] {f.line}" for f in c.findings]}
            for c in inv.logs.containers if c.namespace == namespace
        ],
        "events": [f"{e.object} {e.reason} x{e.count}: {e.message}" for e in inv.events.findings if e.namespace == namespace],
        "deployments": [
            {"name": d.name, "issues": d.issues} for d in inv.deployments.unhealthy_deployments if d.namespace == namespace
        ],
        "network": [f"{i.type} {i.name}: {i.message}" for i in inv.network.service_issues if i.namespace == namespace],
        "dns": inv.network.dns.model_dump(),
        "failed_steps": inv.summary.failed_steps,
    }
    record["namespace_healthy"] = not (pods or record["evidence"]["deployments"] or record["evidence"]["network"])

    try:
        diagnosis = diagnose(inv)
    except LLMError as exc:
        record["ai_error"] = str(exc)
        return record

    issues = [] if diagnosis.healthy else [diagnosis, *diagnosis.other_issues]
    mine = [i for i in issues if any(_in_namespace(r, namespace) for r in i.affected_resources)]
    record["ai"] = {
        "model": diagnosis.model,
        "cluster_healthy": diagnosis.healthy,
        "summary": diagnosis.summary,
        "issues_for_namespace": [
            {
                "title": i.title, "severity": i.severity, "affected_resources": i.affected_resources,
                "root_cause": i.root_cause, "explanation": i.explanation, "evidence": i.evidence,
                "fix": i.fix, "kubectl_commands": i.kubectl_commands, "prevention": i.prevention,
                "confidence": i.confidence, "confidence_reasons": i.confidence_reasons, "warnings": i.warnings,
            }
            for i in mine
        ],
        "other_issues": [f"{i.title} ({', '.join(i.affected_resources)})" for i in issues if i not in mine],
    }
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--label", required=True)
    options = parser.parse_args()

    record = run(options.cluster, options.namespace, options.label)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{options.label}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    print(f"\n=== {options.label}: {record['cluster']} / {options.namespace}")
    if "error" in record:
        print("Investigation failed:", record["error"])
        return 1
    print("Kubernetes status:", [(s["pod"], s["status"]) for s in record["kubernetes_status"]] or "no problem pods")
    for d in record["evidence"]["deployments"]:
        print("Deployment:", d["name"], d["issues"])
    for n in record["evidence"]["network"]:
        print("Network:", n)
    print("Namespace healthy:", record["namespace_healthy"])
    if "ai_error" in record:
        print("AI failed:", record["ai_error"])
        return 1
    ai = record["ai"]
    print("AI summary:", ai["summary"])
    for i in ai["issues_for_namespace"]:
        print(f"\n  [{i['severity']}] {i['title']}  ({i['confidence']}%)")
        print("   resources :", ", ".join(i["affected_resources"]))
        print("   root cause:", i["root_cause"])
        print("   fix       :", i["fix"])
        for c in i["kubectl_commands"]:
            print("   $", c)
    if ai["other_issues"]:
        print("\n  Other issues outside the namespace:", ai["other_issues"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
