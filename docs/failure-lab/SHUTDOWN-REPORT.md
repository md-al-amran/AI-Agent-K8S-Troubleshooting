# Lab Shutdown Report

**Stopped:** 2026-11-17 22:11–22:13 UTC (2026-11-18 04:11 local, +06:00)
**Backups:** `backups/lab-2026-11-18/` at the repo root (ignored by git; it contains the test Secret)

## Clusters

| Cluster (context) | Platform | Node container | IP on `kind` network | API port | Shutdown status |
|---|---|---|---|---|---|
| kind-kubernetes-demo-cluster | kind v0.33 (Docker Desktop, WSL2), Kubernetes v1.37.0, 1 node | `kubernetes-demo-cluster-control-plane` | 172.18.0.2 | 127.0.0.1:50170 | Stopped. Exit 137: force-stopped after the 60 s grace period |
| kind-ecommerce-cluster-01 | same | `ecommerce-cluster-01-control-plane` | 172.18.0.4 | 127.0.0.1:53025 | Stopped. Exit 137 (same) |
| kind-ecommerce-cluster-02 | same | `ecommerce-cluster-02-control-plane` | 172.18.0.5 | 127.0.0.1:53105 | Stopped. Exit 137 (same) |
| devops-assessment-aks | Azure AKS | n/a | n/a | n/a | **Not touched.** Not a lab cluster, and already unreachable before shutdown (DNS name doesn't resolve) |

Command used: `docker stop -t 60 <the three node containers>`. kind nodes default to a 1-second stop timeout, which is why `-t 60` was used. systemd inside the nodes still didn't finish within 60 s, so Docker force-stopped them. etcd's write-ahead log is designed to survive that, and tomorrow's resume steps check it.

Not done (on purpose): no `kind delete`, `docker rm`, volume or network removal, `kubectl drain`, context switch, or kubeconfig edit.

## Preserved

| What | Where it lives | Survives the stop? |
|---|---|---|
| All Kubernetes objects (Namespaces, Deployments, ReplicaSets, Pods, Services, ConfigMaps, Secrets) | etcd inside each node's Docker volume (`728417e0…`, `e445874b…`, `c08a60e4…`) | Yes |
| Injected failures (they are part of the object specs) | etcd | Yes, see the table below |
| kubeconfig contexts (all 4) and the current context (`kind-ecommerce-cluster-02`) | `~/.kube/config` | Yes, unchanged |
| `kind` Docker network (172.18.0.0/16) | Docker | Yes |
| AI agent config: `backend/.env`, `frontend/.env.local`, root `.env` | Repo folder | Yes |
| Investigation history and realtime | InsForge (cloud) | Yes, not affected |
| Lab manifests, test report, raw results | `docs/failure-lab/` | Yes |
| YAML backup of every lab namespace, plus status snapshots | `backups/lab-2026-11-18/<context>/` | Yes |
| PersistentVolumes / PVCs | none exist in any lab cluster | n/a |

### Failure scenarios at shutdown

| Cluster | Namespace / resource | Scenario | State at shutdown | Expected after resume |
|---|---|---|---|---|
| demo | `ai-agent-failure-test/crashloop-nginx` | CrashLoopBackOff | CrashLoopBackOff (10 restarts) | Same: the command still exits 1 |
| demo | `ai-agent-failure-test/imagepull-nginx` | ImagePullBackOff | ImagePullBackOff | Same: the tag still doesn't exist |
| demo | `ai-agent-failure-test/pending-nginx` | Pending | Pending | Same: no node has the label |
| demo | `default/nginx-crash` (yours, pre-existing) | StartError | StartError | Same |
| cluster-01 | `ecommerce/database` | F1: `POSTGRES_PASSWORD` removed | New pod CrashLoopBackOff; old replica serving | Same (spec unchanged) |
| cluster-02 | `ecommerce/backend-api` | F4: `APP_MODE` typo | **Already fixed before shutdown.** ConfigMap patched to `production` and backend-api restarted at 21:57 UTC from your machine (the agent's recommended commands). Healthy, 1/1 | Healthy |
| — | networking / connectivity scenarios (F5–F8) | — | **Never injected** (the test was stopped after F1/F4) | — |

## What won't survive (expected, not a problem)

- **Pod-local data.** Postgres has no PersistentVolume, so its data lives in the container and is recreated empty on restart. The shop's catalog comes from a ConfigMap, so nothing visible is lost.
- **Pod IPs and container IDs** change when kubelet recreates containers. Service IPs and DNS names stay the same.
- **Events** expire after about 1 hour. Tomorrow's events will be new restart events. Today's events are saved in `backups/…/events-*.txt`.
- **Restart counts** keep growing. Back-off timers reset, so failing pods re-enter CrashLoopBackOff within a minute or two.

## Still running

| Process | Why |
|---|---|
| `ai-kubernetes-agent-backend-1` (port 8000), `ai-kubernetes-agent-frontend-1` (port 3000) | You chose "stop clusters only". The backend keeps IP 172.18.0.3 on the `kind` network. Until the clusters are back, the dashboard shows them as Unreachable. |
| Docker Desktop | Needed to resume |

## Risks for tomorrow

1. **Node IPs.** Docker reassigns IPs on start. Starting in the order below should give each node its original IP back (.2, .4, .5, with the backend holding .3). kind single-node clusters usually tolerate an IP change anyway, but keeping them avoids certificate or kubelet surprises.
2. **Machine or Docker Desktop restart overnight.** The node containers use `restart: on-failure:1` and the agent has no restart policy, so nothing starts by itself. That's fine; just follow the order below, including the agent's backend.
3. **Unclean stop (exit 137).** If an API server doesn't come up, check `docker logs <node>` and `docker exec <node> journalctl -u kubelet --no-pager | tail`. etcd normally recovers on its own.
4. **Your current context is `kind-ecommerce-cluster-02`** (it was changed during the session). The resume steps always pass `--context` explicitly.

## Resume procedure (tomorrow, when you ask)

```bash
# 0. Docker Desktop running
docker info --format '{{.ServerVersion}}'

# 1. If Docker restarted overnight, start the agent backend's network slot first (only if it's stopped):
#    order demo -> backend -> cluster-01 -> cluster-02 reproduces IPs .2/.3/.4/.5
docker start kubernetes-demo-cluster-control-plane
docker ps --filter name=ai-kubernetes-agent-backend-1 --format '{{.Status}}' | grep -q Up || \
  docker compose -f docker-compose.yml -f docker-compose.kind.yml start backend
docker start ecommerce-cluster-01-control-plane
docker start ecommerce-cluster-02-control-plane

# 2. Same IPs as before?
docker network inspect kind --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}'

# 3. Nodes Ready (allow 1-2 minutes)
for c in kind-kubernetes-demo-cluster kind-ecommerce-cluster-01 kind-ecommerce-cluster-02; do
  kubectl --context $c wait node --all --for=condition=Ready --timeout=180s; done

# 4. Compare with the saved snapshot
for c in kind-kubernetes-demo-cluster kind-ecommerce-cluster-01 kind-ecommerce-cluster-02; do
  kubectl --context $c get pods,deploy,svc -A -o wide; done
#    vs backups/lab-2026-11-18/<context>/status-all.txt

# 5. Failure scenarios still present (expect the states in the table above). Do NOT fix them.
# 6. App connectivity (cluster-02 healthy; cluster-01's old database replica still serves)
kubectl --context kind-ecommerce-cluster-01 -n ecommerce run curl-check --rm -i --restart=Never --image=curlimages/curl:8.11.1 --quiet -- curl -s -m 10 http://frontend/api/products
# 7. Agent can reach all lab clusters: dashboard cluster list, or
cd backend && python -m scripts.failure_lab --cluster kind-ecommerce-cluster-01 --namespace ecommerce --label resume-check-01
```

Nothing in these steps deletes, resets or fixes anything. If a cluster won't come back, I'll explain why before trying anything else.
