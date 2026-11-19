"""Run real Kubernetes failure scenarios through the agent and check its diagnosis.

For each scenario in docs/examples/scenarios:
  1. kubectl apply the broken workload (into its own namespace)
  2. wait until the failure actually shows up in the cluster
  3. run the same investigation + AI diagnosis as POST /investigate
  4. check the root cause and fix mention the right things
  5. delete the namespace

Usage (from the backend folder, with the venv active):
  python -m scripts.run_scenarios                      # all scenarios, current kubeconfig context
  python -m scripts.run_scenarios --cluster kind-demo  # another context
  python -m scripts.run_scenarios --only oom --keep    # one scenario, keep it running afterwards

This script creates and deletes namespaces, so only point it at a test cluster.
"""

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.ai.llm_client import LLMError
from app.ai.reasoner import diagnose
from app.kubernetes.clusters import cluster_args, find_cluster
from app.kubernetes.executor import use_cluster
from app.kubernetes.network import inspect_network
from app.kubernetes.pods import fetch_pods, inspect_pods
from app.models.diagnosis import IssueDiagnosis
from app.services.investigation import investigate_cluster

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "docs" / "examples" / "scenarios"
WAIT_SECONDS = 240
POLL_SECONDS = 5


@dataclass
class Scenario:
    key: str
    file: str
    namespace: str
    expect_detected: str  # what the investigation layer must find (pod status or network issue type)
    root_cause_any: list[str]  # the AI root cause must mention one of these
    fix_any: list[str]  # the AI fix or commands must mention one of these


SCENARIOS = [
    Scenario("crashloop", "01-crashloop-missing-env.yaml", "scenario-crashloop", "CrashLoopBackOff",
             ["database_url"], ["database_url"]),
    Scenario("imagepull", "02-imagepull-wrong-tag.yaml", "scenario-imagepull", "ImagePullBackOff",
             ["tag", "image"], ["set image", "image"]),
    Scenario("oom", "03-oomkilled.yaml", "scenario-oom", "OOMKilled",
             ["memory", "oom"], ["memory", "limit"]),
    Scenario("selector", "04-selector-mismatch.yaml", "scenario-selector", "SelectorMismatch",
             ["selector", "label"], ["selector", "label"]),
]


def kubectl(context: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", context, *args], capture_output=True, text=True, check=False)


def detected(scenario: Scenario) -> bool:
    """Has the failure shown up yet? Uses the same inspectors as the agent."""
    pods = fetch_pods()
    if scenario.expect_detected == "SelectorMismatch":
        network = inspect_network(pods)
        return any(i.namespace == scenario.namespace and i.type == "SelectorMismatch" for i in network.service_issues)
    report = inspect_pods(pods)
    return any(
        p.namespace == scenario.namespace and scenario.expect_detected in p.reasons for p in report.problematic_pods
    )


def text_of(issue: IssueDiagnosis) -> tuple[str, str]:
    root = f"{issue.title} {issue.root_cause} {issue.explanation}".lower()
    fix = f"{issue.fix} {' '.join(issue.kubectl_commands)}".lower()
    return root, fix


def run(scenario: Scenario, context: str, keep: bool) -> dict:
    print(f"\n=== {scenario.key}: {scenario.file}")
    applied = kubectl(context, "apply", "-f", str(SCENARIO_DIR / scenario.file))
    if applied.returncode != 0:
        return {"key": scenario.key, "passed": False, "note": f"kubectl apply failed: {applied.stderr.strip()}"}

    try:
        # 2. Wait for the failure to appear
        deadline = time.monotonic() + WAIT_SECONDS
        while not detected(scenario):
            if time.monotonic() > deadline:
                return {"key": scenario.key, "passed": False, "note": f"{scenario.expect_detected} never appeared"}
            time.sleep(POLL_SECONDS)
        print(f"   failure is live ({scenario.expect_detected}), investigating...")

        # 3. Investigate + diagnose, exactly like the API does
        investigation = investigate_cluster(cluster_name=context)
        try:
            diagnosis = diagnose(investigation)
        except LLMError as exc:
            return {"key": scenario.key, "passed": False, "note": f"AI failed: {exc}"}

        # 4. Find the issue about this scenario's namespace and check it
        issues = [diagnosis, *diagnosis.other_issues]
        mine = [i for i in issues if any(f"/{scenario.namespace}/" in r or r.startswith(f"{scenario.namespace}/")
                                         for r in i.affected_resources)] or issues
        for issue in mine:
            root, fix = text_of(issue)
            if any(w in root for w in scenario.root_cause_any) and any(w in fix for w in scenario.fix_any):
                return {"key": scenario.key, "passed": True, "issue": issue}
        return {"key": scenario.key, "passed": False, "issue": mine[0], "note": "root cause or fix missed the point"}
    finally:
        if not keep:
            # Wait for the namespace to go away so the next scenario starts from a clean cluster.
            print(f"   cleaning up namespace {scenario.namespace}...")
            kubectl(context, "delete", "namespace", scenario.namespace, "--wait=true", "--timeout=180s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cluster", help="kubeconfig context (default: current context)")
    parser.add_argument("--only", choices=[s.key for s in SCENARIOS], action="append")
    parser.add_argument("--keep", action="store_true", help="do not delete the scenario namespaces")
    options = parser.parse_args()

    cluster = find_cluster(options.cluster)
    print(f"Cluster: {cluster.name} ({cluster.server})")
    scenarios = [s for s in SCENARIOS if not options.only or s.key in options.only]

    results = []
    with use_cluster(cluster_args(cluster)):
        for scenario in scenarios:
            results.append(run(scenario, cluster.name, options.keep))

    print("\n" + "=" * 100)
    for result in results:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"\n[{mark}] {result['key']}")
        issue = result.get("issue")
        if issue:
            print(f"   Root cause : {issue.root_cause}")
            print(f"   Fix        : {issue.fix}")
            for command in issue.kubectl_commands:
                print(f"   $ {command}")
            print(f"   Confidence : {issue.confidence}% ({issue.confidence_level})")
        if result.get("note"):
            print(f"   Note       : {result['note']}")
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
