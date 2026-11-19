# Lab Recovery Report

**Resumed:** 2026-11-18 ~06:00–06:10 UTC (12:00–12:10 local, +06:00)
**Follows:** [SHUTDOWN-REPORT.md](SHUTDOWN-REPORT.md) (stopped 2026-11-17 22:11–22:13 UTC)
**Result:** All three lab clusters are back, nothing was lost, every failure scenario is still in place, and the agent can reach all three clusters.

## What happened differently from the plan

The resume procedure assumed I would start the containers in order (demo → backend → cluster-01 → cluster-02). That didn't happen:

1. **Docker Desktop had restarted overnight.** Its UI process started at 12:03 local, and the engine answered within 5 seconds of my first check.
2. **Docker restarted the node containers by itself as soon as the engine came up.** Their `on-failure:1` restart policy treated last night's forced stop (exit 137) as a failure. The shutdown report's risk #2 said nothing would start by itself. That was wrong for the nodes, and right for the agent containers.
3. **The agent containers were stopped** (Exited 255, because Docker shut down) and had to be started by hand.

Because the nodes started together with no backend running, two IPs swapped:

| Container | IP before | IP now | Effect |
|---|---|---|---|
| `kubernetes-demo-cluster-control-plane` | 172.18.0.2 | 172.18.0.2 | — |
| `ai-kubernetes-agent-backend-1` | 172.18.0.3 | **172.18.0.5** | None. Other containers don't address it by IP |
| `ecommerce-cluster-01-control-plane` | 172.18.0.4 | 172.18.0.4 | — |
| `ecommerce-cluster-02-control-plane` | 172.18.0.5 | **172.18.0.3** | None. The node came up Ready with InternalIP .3. kubectl uses 127.0.0.1:53105 and the agent uses the container name |

I left the swap as it was. Restarting cluster-02 just to get .5 back would have added risk for no benefit.

## Checks

| # | Check | Result |
|---|---|---|
| 1 | Docker engine up | ✅ 29.6.1 |
| 2 | Nodes Ready (`kubectl wait --for=condition=Ready`) | ✅ all 3, Kubernetes v1.37.0. etcd recovered from the forced stop without intervention |
| 3 | kube-system / local-path pods | ✅ all Running on all 3 clusters |
| 4 | Pods vs `backups/lab-2026-11-18/*/status-all.txt` | ✅ Same pod names (no pods recreated, no ReplicaSets changed), same states |
| 5 | Deployments / Service ClusterIPs | ✅ 4/4 Deployments 1/1 on both shop clusters. All 8 Service ClusterIPs match the backup |
| 6 | Failures still present (not fixed) | ✅ see below |
| 7 | Shop inside each cluster (`curl http://frontend/api/products` from a pod) | ✅ cluster-01 HTTP 200, cluster-02 HTTP 200, 3 products each |
| 8 | Agent app | ✅ backend healthy on :8000, frontend HTTP 200 on :3000 |
| 9 | Agent can reach the clusters (`list_clusters_with_status()` run inside the backend container) | ✅ demo, cluster-01, cluster-02 = up. `devops-assessment-aks` = down (DNS doesn't resolve, same as before shutdown) |
| 10 | kubeconfig | ✅ unchanged; current context is still `kind-ecommerce-cluster-02` |

## Failure scenarios after resume

| Cluster | Resource | Scenario | Now | Cause still present |
|---|---|---|---|---|
| demo | `ai-agent-failure-test/crashloop-nginx` | CrashLoopBackOff | Error / back-off, 14 restarts | `open() "/etc/nginx/conf.d/site.conf" failed` |
| demo | `ai-agent-failure-test/imagepull-nginx` | ImagePullBackOff | ImagePullBackOff | `nginx:1.27-doesnotexist: not found` |
| demo | `ai-agent-failure-test/pending-nginx` | Pending | Pending | nodeSelector `disktype=nvme-gpu-test`, 0/1 nodes match |
| demo | `default/nginx-crash` (yours) | StartError | StartError | unchanged (exit 128, runc create failed) |
| cluster-01 | `ecommerce/database` | F1 | New pod `database-695f999cc7-q22hb` CrashLoopBackOff (12 restarts). Old replica `database-86ddb4bd97-8785v` 1/1 serving | new ReplicaSet has no env vars: "superuser password is not specified" |
| cluster-02 | `ecommerce/backend-api` | F4 | Healthy 1/1 | Stays fixed (`APP_MODE: production`), as expected |

## Expected changes (not problems)

- Every container restarted once. The frontends restarted 3 times because they came up before their dependencies were ready, then settled.
- Postgres on both shop clusters started with an empty database (no PersistentVolumes). The catalog comes from a ConfigMap, so the shop looks the same.
- Pod IPs changed, and yesterday's events have expired. They're still in `backups/lab-2026-11-18/*/events-*.txt`.

## Not done

- No failures were fixed, and no Kubernetes objects were created except two temporary `curl-check` pods, which were deleted afterwards.
- Full agent investigations were run afterwards from the dashboard; see "Full agent investigations after resume" above.

## Full agent investigations after resume (dashboard, saved to InsForge history)

Run by you from the dashboard (signed in; `AUTH_REQUIRED=true`). Model `nvidia/nemotron-3.5-super-vl:free` via OpenRouter. Rows checked in `public.investigations`.

| Started (UTC) | Cluster | History status | AI time | Main finding (confidence) | Correct? |
|---|---|---|---|---|---|
| 06:27:07 | cluster-01 | **`running` (stuck)** | — | none. OpenRouter unreachable (`RemoteProtocolError`, then `ConnectError` ×2, 3 attempts) | n/a, see bug 1 |
| 09:07:04 | cluster-02 | success | 72 s | "Control-plane node NotReady; frontend crash-loops" (78%), severity high | **✗ False alarm**, see bug 2 |
| 09:09:07 | demo | success | 113 s | crashloop-nginx: missing `site.conf` (95%). Also: imagepull-nginx bad tag (97%), pending-nginx selector mismatch (92%), `default/nginx-crash` Windows shell path as entrypoint (90%) | ✓ all 4 found. crashloop-nginx is still only partly right (symptom, not the overridden command), same as yesterday |
| 09:11:33 | cluster-01 | success | 75 s | F1: Postgres has no `POSTGRES_PASSWORD` (95%), severity critical | ✓ root cause. Also flagged the healthy frontend as crash-looping (40%), see bug 2 |

| 09:27:01 | cluster-01 | success | 43 s (evidence collection 2.9 s) | F1 again: "POSTGRES_PASSWORD is not set" (95%), critical. Run by the scripted GIF recorder | ✓ root cause. Healthy frontend flagged again (50%), see bug 2 |

Every successful run collected all 6 steps (pods, logs, events, deployments, network, ai).

### Bugs found

1. **History row left at `running` when the AI call fails during a network outage.** The API still returned the evidence (`POST /investigate` 200, status partial), but `history.finish("partial")` never landed. It's best-effort and probably hit the same outage. The row will show "Investigating..." forever. Fix idea: retry `finish()`, or mark rows still `running` after N minutes as `error` when history loads.
2. **False alarms on healthy clusters are back on the dashboard.** Two causes:
   - **The dashboard runs a stale build.** The backend image was built at 2026-11-17 21:19 UTC. The stale-event filter (`app/kubernetes/correlate.py`, written 21:46 UTC) isn't in the container at all: `drop_resolved_events` appears 0 times in `/app/app/services/investigation.py`. Yesterday's healthy-cluster retest ran through `scripts.failure_lab` on the host, so it tested the new code, but the dashboard never got it. So an 11-second node blip at 09:02:22–09:02:33 (node Ready again 4½ min before the run) was reported as a NotReady node. Fix: `docker compose -f docker-compose.yml -f docker-compose.kind.yml up -d --build backend`.
   - **Old restarts count as a crash loop, in the repo code too.** In [`pods.py:101`](../../backend/app/kubernetes/pods.py#L101), a container with ≥3 restarts and a failed last exit is labelled `CrashLoopBackOff`, even if it has been Running and Ready for hours. Both frontends restarted 3 times during the cold start, so both get flagged. Fix idea: require the container to be not running, or its last termination to be recent (e.g. < 10 min).

Neither bug was fixed, and no image was rebuilt. Both are code changes for you to approve.

## For next time

Update the shutdown procedure: either accept that nodes start automatically when Docker starts, or set `docker update --restart=no <nodes>` before stopping them, so the start order (and the original IPs) can be controlled.
