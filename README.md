# AI Kubernetes Agent

On-demand Kubernetes troubleshooting. `POST /investigate` collects evidence from the cluster with kubectl (pods, logs, events, deployments, networking). An LLM acting as a senior SRE (OpenRouter, using the key from InsForge) then returns the root cause, fix, kubectl commands, and a confidence score. A dashboard (sign-in, live progress, history) runs on InsForge auth, database and realtime. See [docs/architecture.md](docs/architecture.md).

## Layout

```text
backend/     FastAPI orchestrator
frontend/    Next.js UI
docs/        Architecture notes
prompts/     Prompt files for later steps
```

## Setup (once)

1. **InsForge schema:** run [docs/insforge/schema.sql](docs/insforge/schema.sql) in the InsForge SQL editor.
2. **Backend:** copy `backend/.env.example` to `backend/.env`, then set `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` and `INSFORGE_BASE_URL`.
3. **Frontend:** copy `frontend/.env.example` to `frontend/.env.local`, then set the InsForge URL and anon key.
4. **Docker:** copy `.env.example` to `.env` (same two InsForge values; Docker uses them to build the frontend).

## Run with Docker

```bash
docker compose up --build
```

Open http://localhost:3000 and create an account (InsForge emails you a 6-digit code). Every cluster in your kubeconfig is listed with its status. Pick one and click **Investigate Cluster**.

- Frontend: http://localhost:3000
- Health: http://localhost:8000/health
- Investigate: `curl -X POST http://localhost:8000/investigate`
- API docs: http://localhost:8000/docs

The backend container reads your kubeconfig from `~/.kube` (read-only). Set `KUBE_CONFIG_DIR` to use another folder. This works for remote clusters and Docker Desktop Kubernetes. Kubeconfigs that rely on cloud login plugins (`aws`, `gke-gcloud-auth-plugin`, `kubelogin`) need those tools in the image, so run the backend locally for those.

### Local kind clusters

kind clusters listen on `127.0.0.1`, which a container can't reach. Add the kind override. It joins kind's Docker network and reaches every kind cluster in your kubeconfig by its node name:

```bash
docker compose -f docker-compose.yml -f docker-compose.kind.yml up --build
```

## Local development

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Running locally uses your normal kubectl setup, so kind and cloud clusters work without extra steps. kubectl must be on your PATH.

Frontend:

```bash
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

Copy `backend/.env.example` to `backend/.env` and set `OPENROUTER_API_KEY` to the OpenRouter key from your InsForge dashboard. Without it, `/investigate` still returns the evidence, with `status: "partial"`.

## Test with real failures

Four ready-made broken workloads (CrashLoopBackOff, ImagePullBackOff, OOMKilled, selector mismatch) are in [docs/examples/scenarios/](docs/examples/scenarios/). To run all four through the agent and check the diagnoses (test clusters only, since it creates and deletes namespaces):

```bash
cd backend
python -m scripts.run_scenarios
```
