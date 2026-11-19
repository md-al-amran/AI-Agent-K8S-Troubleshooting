# AI Kubernetes Agent: Troubleshooting Test Report

**Date:** 2026-11-17 (UTC)
**Agent:** this repo's investigation layer and AI diagnosis, the same code path as `POST /investigate`
**Model:** `nvidia/nemotron-3.5-super-vl:free` via OpenRouter
**Raw results:** [`results/`](results/) (one JSON file per run: evidence collected and the full AI answer)

## Scope and approvals

| Phase | Status | Notes |
|---|---|---|
| Inspect the existing cluster first | Done (read only) | 1 node, 8 CPU, about 7.6 GiB. Only system namespaces, plus one workload already present: `default/nginx-crash` (`StartError`). It was left untouched. |
| 1. Three failing pods on the existing cluster | Done (approved) | Namespace `ai-agent-failure-test` |
| 2. Create `ecommerce-cluster-01` and `ecommerce-cluster-02` | Done (approved) | Local kind clusters, one node each, isolated from the existing cluster |
| 3. Deploy the demo shop to both | Done (approved) | frontend (nginx), backend-api, product-service, database (Postgres) in namespace `ecommerce`. Verified end to end: `curl frontend/api/products` returns the catalog in both clusters |
| 4. Inject failures | **Partial** | F1 and F4 injected (approved). You stopped the run after F1/F4, so F2, F3, F5–F8 were not run |
| 5. Validate the agent | Done for Phase 1, F1, F4 | |
| Remediation | **Not applied** | You declined the F1 and F4 fixes and chose "diagnosis only" for the rest, so no recovery was verified |

## Results

| # | Cluster | Namespace | Component | Injected failure | Expected status | Actual status | Root cause found by the agent | Recommended fix | Correct diagnosis? | Fix resolved it? |
|---|---|---|---|---|---|---|---|---|---|---|
| P1-a | kind-kubernetes-demo-cluster | ai-agent-failure-test | `crashloop-nginx` pod | NGINX command prints an error and exits 1 | CrashLoopBackOff | CrashLoopBackOff (3 restarts) | nginx exits because `/etc/nginx/conf.d/site.conf` is missing (from the container's own log line), 95% | Provide the config file via a ConfigMap and recreate the pod | **Partly.** State, pod and log evidence are correct, and the root cause matches what the container logged. The real cause is the overridden `command`, which the agent can't see (it doesn't read pod specs). | Not applied (diagnosis only) |
| P1-b | kind-kubernetes-demo-cluster | ai-agent-failure-test | `imagepull-nginx` pod | Image `nginx:1.27-doesnotexist` | ImagePullBackOff | ImagePullBackOff / ErrImagePull | Tag `nginx:1.27-doesnotexist` does not exist in the registry, 98% | Change the image to a valid tag (e.g. `nginx:1.27`) | **Yes** | Not applied (diagnosis only) |
| P1-c | kind-kubernetes-demo-cluster | ai-agent-failure-test | `pending-nginx` pod | `nodeSelector: disktype=nvme-gpu-test` (no node has it) | Pending | Pending, "0/1 nodes … didn't match node affinity/selector" | Node selector/affinity matches no node, 95% | Relax the selector or label a node, then redeploy | **Yes** | Not applied (diagnosis only) |
| F1 | kind-ecommerce-cluster-01 | ecommerce | database (Postgres) | `POSTGRES_PASSWORD` removed from the Deployment | CrashLoopBackOff | New pod CrashLoopBackOff; old replica still serving | Postgres starts without `POSTGRES_PASSWORD` and refuses to initialize, 95% | `kubectl set env deployment/database POSTGRES_PASSWORD=<secure-password>` | **Yes** | **Declined by you.** Not verified |
| F4 | kind-ecommerce-cluster-02 | ecommerce | backend-api | ConfigMap `backend-config` set to `APP_MODE=prodution` (typo) + restart | CrashLoopBackOff | New pod CrashLoopBackOff; old replica still serving | ConfigMap `backend-config` has `APP_MODE='prodution'`, a typo for `production`, 95% | Patch the ConfigMap to `production`, `rollout restart`, `rollout status` (exact, runnable commands) | **Yes** | **Yes.** Declined in this session, but applied afterwards from your machine at 21:57 UTC with the agent's exact commands. backend-api recovered (1/1 Ready, ConfigMap `APP_MODE=production`) |
| F2 | ecommerce-cluster-01 | ecommerce | frontend | Image tag typo | ImagePullBackOff | Not run | | | | |
| F3 | ecommerce-cluster-01 | ecommerce | product-service | Requests 64Gi memory | Pending | Not run | | | | |
| F5 | ecommerce-cluster-02 | ecommerce | product-service Service | Selector `app=product-svc` | Running; service has no endpoints | Not run | | | | |
| F6 | ecommerce-cluster-02 | ecommerce | backend-api Service | `targetPort: 8000` (app listens on 8080) | Frontend NotReady | Not run | | | | |
| F7 | ecommerce-cluster-01 | ecommerce | frontend → backend | nginx proxies to `backend-api:9090` | Frontend NotReady | Not run | | | | |
| F8 | ecommerce-cluster-02 | ecommerce | backend-api DNS | Pod `dnsPolicy: None` with a dead nameserver | backend NotReady, DNS errors in logs | Not run | | | | |

### What the agent did for each scenario

| Capability | P1-a | P1-b | P1-c | F1 | F4 |
|---|---|---|---|---|---|
| Named the right cluster, namespace and pod | ✓ | ✓ | ✓ | ✓ | ✓ (also the ConfigMap) |
| Detected the right Kubernetes error state | ✓ | ✓ | ✓ | ✓ | ✓ |
| Read and used pod logs | ✓ current run | n/a (never started) | n/a (never scheduled) | ✓ previous run | ✓ previous run |
| Used Kubernetes events | ✓ BackOff | ✓ Failed/BackOff | ✓ FailedScheduling | ✓ BackOff, Unhealthy | ✓ BackOff, Unhealthy |
| Checked Deployments, Services, networking | ✓ (all healthy) | ✓ | ✓ | ✓ | ✓ |
| Found the actual root cause | Partly | ✓ | ✓ | ✓ | ✓ |
| Recommended a fix | ✓ | ✓ | ✓ | ✓ | ✓ |
| Fix commands would run as written | ✗ | ~ | ✗ | ~ | ✓ |
| Explained the fix | ✓ | ✓ | ✓ | ✓ | ✓ |
| Verified recovery after the fix | not done | not done | not done | declined | ✓ (applied by you; recovered) |

In the "Fix commands" row:
- **✓** means the commands run as written.
- **~** means the commands would work once a placeholder is filled in.
- **✗** means the commands would be rejected.
  - P1-a: its `kubectl patch pod` adds volumes, which can't be changed on a running pod.
  - P1-c: its command patches `affinity`, but the pod uses `nodeSelector`, and neither can be changed on a running pod.

## Baseline finding: false positives on healthy clusters (fixed during the test)

The first baseline run on the two freshly deployed, **fully healthy** clusters reported failures that didn't exist: "database not accepting connections", "frontend not listening on port 80", "control-plane node NotReady", "taints block CoreDNS".

- **Cause:** the events step passed along every stored Warning event, including readiness failures from the first seconds of startup and node bootstrap events. The model had no current time and no notion of event age.
- **Fix:** I changed the agent's code; no cluster was touched.
  - `app/kubernetes/correlate.py` now drops events about things that have since recovered (pod healthy or gone, node Ready). Other events are kept for 60 minutes.
  - Each event now has `age_minutes`, and the prompt now gives the collection time and says to judge the *current* state.
  - A running container that fails readiness now counts as `NotReady` after 1 minute of running, instead of after the pod is 5 minutes old, so a freshly restarted broken pod is caught.
- **Retest:**
  - cluster-01: 10 stale event groups ignored. Reported healthy, with no AI call needed.
  - cluster-02: 13 ignored. The AI said no active incident.
  - The failure runs (P1, F1, F4) were done after this fix.

## Summary

**Diagnosis accuracy: 4 of 5 fully correct, 1 partly correct (5/5 found the right state, pod and evidence).**
- The agent always named the right cluster, namespace and pod, and the right Kubernetes state.
- It read the right logs (including `--previous` for crashed containers), used the matching events, and separated each problem from unrelated ones. It also correctly reported the pre-existing `default/nginx-crash` pod as a separate issue.
- Confidence was 95–98% in all cases, backed by specific facts (log line, restart count, event count).

**Remediation: 1 verified.** F4's fix (the agent's exact commands) was applied from your machine after the session and backend-api recovered. No other fixes were applied. Of the five recommendations:
- F4's commands would run as written.
- F1's and P1-b's would run once a placeholder value is filled in.
- P1-a's and P1-c's would be rejected by Kubernetes.

**Coverage:** 5 of 11 planned scenarios ran. The networking and connectivity scenarios (selector mismatch, targetPort, frontend → backend, DNS) were not exercised in this run. An earlier automated test (`scripts/run_scenarios.py`) did pass a selector-mismatch case at 95%.

## Areas to improve

1. **Read the pod spec.** The agent sees status, logs and events, but not `command`/`args`, env and secret references, `nodeSelector`/affinity, or `dnsPolicy`. That's why P1-a stopped at the symptom the container printed, why F1's fix used a placeholder instead of the existing `database-credentials` Secret, and why F8 (pod DNS config) would be hard to pin down.
2. **Know what can't be changed.** Two suggested commands patch pod fields Kubernetes won't allow. The agent sometimes contradicts itself ("immutable … so patch the pod"). Add a prompt rule: for a bare pod, use `kubectl delete pod` and re-apply; for an owned pod, change the Deployment. A check in `ai/fixes.py` could also flag `kubectl patch pod` that touches spec fields.
3. **Recognize a stuck rollout.** In F1 and F4 the old replica kept serving, so the Deployment still showed as available, and the agent called it "critical … taking the database down". The Deployment inspector should flag a new ReplicaSet whose pods are failing while old ones serve, and the prompt should take that into account when grading severity.
4. **Speed.** The free model took 30–120 s per diagnosis. Fine for on-demand use, slow for a live demo. A faster or paid model would cut this to a few seconds.
5. **Verify after fixing.** Add an "investigate again" step after a fix, to show a before/after diff for the affected namespace.

## Current state of the test environment

Everything is still running (no cleanup was approved):

| Where | What's running |
|---|---|
| kind-kubernetes-demo-cluster | namespace `ai-agent-failure-test` with 3 failing pods |
| kind-ecommerce-cluster-01 | shop in `ecommerce`; **F1 active** (database rollout stuck, old replica still serving) |
| kind-ecommerce-cluster-02 | shop in `ecommerce`; **F4 active** (backend-api rollout stuck, old replica still serving) |

Your kubectl current context is back on `kind-kubernetes-demo-cluster`.

## Cleanup

```bash
# Phase 1 test pods (existing cluster): removes only the test namespace
kubectl --context kind-kubernetes-demo-cluster delete namespace ai-agent-failure-test

# The two test clusters: removes the clusters and their kubeconfig contexts
kind delete cluster --name ecommerce-cluster-01
kind delete cluster --name ecommerce-cluster-02
```

To keep the clusters but undo F1 and F4:

```bash
kubectl --context kind-ecommerce-cluster-01 -n ecommerce set env deployment/database --from=secret/database-credentials
kubectl --context kind-ecommerce-cluster-02 -n ecommerce patch configmap backend-config --type merge -p '{"data":{"APP_MODE":"production"}}'
kubectl --context kind-ecommerce-cluster-02 -n ecommerce rollout restart deployment/backend-api
```

## Re-running or finishing the remaining scenarios

The manifests are [`phase1-existing-cluster.yaml`](phase1-existing-cluster.yaml) and [`ecommerce-app.yaml`](ecommerce-app.yaml). Investigate any cluster with:

```bash
cd backend
python -m scripts.failure_lab --cluster <context> --namespace <namespace> --label <name>
```

Injection commands for the scenarios that were not run. Run them one at a time, on a healthy app:

```bash
C01="--context kind-ecommerce-cluster-01 -n ecommerce"; C02="--context kind-ecommerce-cluster-02 -n ecommerce"
# F2 ImagePullBackOff
kubectl $C01 set image deployment/frontend nginx=nginx:1.27-alpne
# F3 Pending
kubectl $C01 set resources deployment/product-service --requests=memory=64Gi --limits=memory=64Gi
# F5 Service selector mismatch
kubectl $C02 patch service product-service -p '{"spec":{"selector":{"app":"product-svc"}}}'
# F6 Wrong targetPort
kubectl $C02 patch service backend-api --type json -p '[{"op":"replace","path":"/spec/ports/0/targetPort","value":8000}]'
# F7 Frontend -> backend connectivity (wrong upstream port in the nginx config)
kubectl $C01 get configmap frontend-config -o yaml | sed 's#backend-api:8080#backend-api:9090#' | kubectl apply -f -
kubectl $C01 rollout restart deployment/frontend
# F8 DNS failure scoped to the backend-api pod
kubectl $C02 patch deployment backend-api -p '{"spec":{"template":{"spec":{"dnsPolicy":"None","dnsConfig":{"nameservers":["10.96.0.250"],"searches":["ecommerce.svc.cluster.local","svc.cluster.local","cluster.local"]}}}}}'
```

To reset a component to healthy, run `kubectl --context <ctx> apply -f ecommerce-app.yaml`. For F8, also remove the DNS override with `kubectl replace -f` on the backend-api Deployment from that file.
