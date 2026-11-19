# Architecture

This is an on-demand troubleshooting app, not a Kubernetes controller.

```text
Frontend
    ↓
FastAPI Backend (Orchestrator)
    ↓
Kubernetes Investigation Layer
    ↓
AI Kubernetes Agent
    ↓
LLM Reasoning (OpenRouter via InsForge)
    ↓
Root Cause + Suggested Fix
    ↓
Frontend Diagnosis
```

## Investigation layer

`POST /investigate` runs `app/services/investigation.py`, which calls each inspector in order:

| Step | Module | kubectl source | Looks for |
|---|---|---|---|
| Pods | `kubernetes/pods.py` | `get pods -A` | CrashLoopBackOff, ImagePullBackOff, Pending, Error, OOMKilled, stuck ContainerCreating or Terminating, NotReady |
| Logs | `kubernetes/logs.py` | `logs --tail` (current or `--previous`) | Exceptions, connection failures, missing config, image or exec failures, startup errors |
| Events | `kubernetes/events.py` | `get events -A` | Warning events grouped by object and reason (FailedScheduling, BackOff, FailedMount, FailedPull, Unhealthy, ...) |
| Deployments | `kubernetes/deployments.py` | `get deployments -A` | Missing replicas, failed rollouts, false conditions |
| Network | `kubernetes/network.py` | `get services,endpointslices -A` | Selector mismatch, no ready endpoints, targetPort mismatch, CoreDNS health |

All kubectl calls go through `kubernetes/executor.py`. It allows only read-only verbs (`get`, `describe`, `logs`, `version`, `cluster-info`), never uses a shell, and applies a timeout.

If one step fails, its report gets an `error` and the others still run. If the cluster can't be reached at all, the endpoint returns HTTP 503 with `status: "error"`.

## AI reasoning layer

After the evidence is collected, `app/ai/reasoner.py` turns it into a diagnosis:

| Step | Module | What it does |
|---|---|---|
| Prompt Builder | `ai/prompt_builder.py` | Senior SRE system prompt, plus the evidence in five fixed sections (pods, logs, events, deployments, networking) with empty fields removed. Asks for one JSON object. |
| LLM Client | `ai/llm_client.py` | Calls OpenRouter `/chat/completions` with HTTPX, `temperature: 0`, JSON mode. Retries timeouts, network errors, 429 and 5xx (up to `OPENROUTER_MAX_RETRIES`). Doesn't retry 401 or 400. |
| Root Cause Analyzer | `ai/reasoner.py` | Parses and validates the reply. The most severe issue goes at the top level, and the rest go in `other_issues`. |
| Fix Recommendation Engine | `ai/fixes.py` | Keeps only real `kubectl` commands, strips `$ ` prompts and backticks, and adds a warning for destructive ones (`delete`, `drain`, `--force`, scale to 0). |
| Confidence Engine | `ai/confidence.py` | Can only lower the model's score: to 40 if the affected resources aren't in the evidence, 50 if it cites no evidence, 75 if an investigation step failed. Adds facts (pod state, restarts, log line, events) to `confidence_reasons`. |

If the cluster is healthy and has no warning events, the model is not called.

The OpenRouter key is read from `OPENROUTER_API_KEY` on the backend only. It can come from InsForge's Model Gateway or a free OpenRouter account.

### Response

```json
{
  "status": "success",
  "diagnosis": {
    "healthy": false,
    "summary": "...",
    "title": "payment-service crash loop",
    "severity": "critical",
    "affected_resources": ["Deployment/ai-agent-test/payment-service"],
    "root_cause": "DATABASE_URL environment variable is not set.",
    "explanation": "...",
    "evidence": ["..."],
    "fix": "...",
    "kubectl_commands": ["kubectl set env deployment/payment-service -n ai-agent-test DATABASE_URL=<value>"],
    "prevention": "...",
    "confidence": 95,
    "confidence_level": "high",
    "confidence_reasons": ["..."],
    "warnings": [],
    "other_issues": [],
    "model": "anthropic/claude-sonnet-5.5"
  },
  "investigation": { "...": "evidence from the investigation layer" },
  "error": null,
  "investigation_id": "uuid of the history row"
}
```

`status` values:

- **`success`:** evidence and diagnosis.
- **`partial`:** evidence collected, but the AI call failed (for example, no key or a rate limit). `error` says why.
- **`error`:** cluster unreachable (HTTP 503).

Without a valid InsForge access token, the endpoint returns HTTP 401.

## Dashboard, auth, history and realtime (InsForge)

FastAPI stays the orchestrator. InsForge is used for three things only:

| Feature | How |
|---|---|
| **Authentication** | The frontend signs in with `@insforge/sdk` (email and password, with a 6-digit email code). It sends the access token to FastAPI as `Authorization: Bearer <token>`. FastAPI checks it with InsForge `GET /api/auth/sessions/current` (`app/insforge/auth.py`). |
| **History** | FastAPI creates a row in `investigations` when a run starts and updates it after each step (`app/insforge/history.py`). It writes with the user's own token, so Row Level Security limits every user to their own rows. The dashboard reads the last 10 rows with the SDK. |
| **Realtime progress** | A database trigger publishes each row change as a `progress` event on the channel `investigations:<user_id>`. The dashboard subscribes to it. A realtime RLS policy only lets users subscribe to their own channel, and clients cannot publish. |

```text
Browser ──sign in──▶ InsForge Auth
   │
   ├── POST /investigate (Bearer token) ──▶ FastAPI ──verify token──▶ InsForge Auth
   │                                          │
   │                                          ├─ insert/update row ──▶ InsForge DB ─trigger─▶ Realtime
   │                                          ├─ kubectl evidence
   │                                          └─ OpenRouter diagnosis
   │
   ◀──── progress events on investigations:<user_id> ─────────────────────── Realtime
```

Saving history is best-effort. If InsForge is unreachable, the investigation still runs and returns its result.

The schema (table, RLS policies, triggers, realtime channel) is in [`docs/insforge/schema.sql`](insforge/schema.sql) and is safe to re-run.

Frontend files:

| File | Role |
|---|---|
| `components/AuthProvider.tsx` | Session state: sign in, sign up, email code, sign out |
| `app/login/page.tsx` | Login and sign-up screen |
| `app/page.tsx` | Protected dashboard |
| `hooks/useRealtimeProgress.ts` | Subscribes to `investigations:<user_id>` |
| `hooks/useHistory.ts` | Reads recent investigations |
| `services/api.ts` | `POST /investigate` with timeout and error messages |

For local curl testing without sign-in, set `AUTH_REQUIRED=false` in `backend/.env`. No history is saved in that mode.

## Choosing a cluster

`GET /clusters` lists every context in the kubeconfig (`kubectl config view`, which redacts credentials) and checks each one in parallel with `kubectl get --raw /readyz`. The dashboard shows them as cards. Click one, then **Investigate Cluster**. `POST /investigate` takes `{"cluster": "<context>"}`. Leave it empty to use the kubeconfig's current context.

The chosen context is applied to every kubectl call through `executor.use_cluster(...)`, so the inspectors didn't change. With `KIND_INTERNAL_NETWORK=true` (set by `docker-compose.kind.yml`), kind clusters are reached at `https://<name>-control-plane:6443` on the `kind` Docker network instead of `127.0.0.1`.

## Errors

Every failure returns a short message plus `hints` ("Please verify: ..."). Stack traces only go to the backend logs.

| Problem | HTTP | Message |
|---|---|---|
| Cluster down or unreachable | 503 | Unable to connect to the Kubernetes cluster |
| No kubeconfig, or no contexts in it | 503 | No Kubernetes clusters found in your kubeconfig |
| kubectl not installed | 503 | kubectl is not installed on the backend |
| Expired credentials, missing RBAC, TLS | 503 | Specific message for each (`kubernetes/errors.py`) |
| Unknown cluster name | 400 | Cluster 'x' is not in your kubeconfig |
| One check fails (for example no permission on events) | 200 | The others still run, and the UI lists the failed checks |
| OpenRouter key, credits, model, rate limit, timeout | 200 `partial` | Evidence is kept, with a specific message for each failure (`ai/llm_client.py`) |
| Not signed in or session expired | 401 | The UI signs out and shows "Your session has expired" |
| Unexpected bug | 500 | Something went wrong on the server |

## Testing real failures

`docs/examples/scenarios/` has four broken workloads, each in its own namespace:

| Scenario | Fault | Expected diagnosis |
|---|---|---|
| `01-crashloop-missing-env.yaml` | App exits because `DATABASE_URL` is unset | Missing env var. Add it (`kubectl set env`) |
| `02-imagepull-wrong-tag.yaml` | Image tag `nginx:1.27.99-typo` | Invalid tag. `kubectl set image` |
| `03-oomkilled.yaml` | Needs ~250Mi, limit 100Mi | Memory limit too low. `kubectl set resources` |
| `04-selector-mismatch.yaml` | Service selects `app=orders-api`, pods are `app=orders` | Selector mismatch. Patch the selector |

`backend/scripts/run_scenarios.py` applies each scenario, waits until the failure is live, runs the same investigation and diagnosis as the API, checks the root cause and fix, and deletes the namespace. Only point it at a test cluster.

```bash
cd backend
python -m scripts.run_scenarios                 # all four, current context
python -m scripts.run_scenarios --only oom --keep
```

Result on kind with `nvidia/nemotron-3.5-super-vl:free`: 4/4 passed, each at 95% confidence.

`docs/examples/broken-workloads.yaml` has the older all-in-one demo (five faults in one namespace).

## Not implemented yet

OAuth sign-in buttons (Google and GitHub are enabled in InsForge but not wired up) and deployment.
