At techjays, I've been exploring whether AI agents can do real on-call work, not just chat.

So I built an AI Kubernetes Agent and a failure lab to test it honestly: break real clusters on purpose, then see if the agent can work out why.

🧪 The lab
3 Kubernetes clusters running a 4-tier demo shop (nginx → API → product service → Postgres). The agent collects evidence with kubectl (pods, logs, events, deployments, networking). An LLM acting as a senior SRE returns the root cause, the fix, kubectl commands and a confidence score.

🛠️ Tech stack
AI model: NVIDIA Nemotron 3.5 Super VL (free tier) via OpenRouter, so switching models is one setting
Backend: Python + FastAPI + kubectl
Frontend: Next.js + TypeScript + Tailwind CSS
Auth, history and live progress: InsForge
Clusters: kind (Kubernetes v1.37) on Docker

🔬 What I broke
CrashLoopBackOff: nginx missing its config file
ImagePullBackOff: an image tag that doesn't exist
Pending: a node selector no node matches
Database outage: Postgres without its password
Config typo: APP_MODE=prodution

📊 The results

1. Diagnosis: 4 of 5 fully correct, 1 partly correct
Every run named the right cluster, pod and state, read the right logs and used the matching events. Confidence: 95–98%. The partial one found the symptom, not the cause, because the agent doesn't read pod specs yet.

2. A right diagnosis isn't a runnable fix
1 of 5 fixes ran exactly as written, and the service recovered. 2 needed a placeholder filled in. 2 would have been rejected by Kubernetes.

3. Speed
Evidence collection takes about 3 seconds. The AI diagnosis takes 30–120 seconds on the free model. With OpenRouter, a faster model is a one-line change.

4. The surprise: false alarms
The first run flagged two healthy clusters as broken, because old startup warnings looked like live incidents. I fixed it by giving every event an age. Then, after an overnight restart, it happened again: the fix was in the code but not in the running container. A fix only counts once it's deployed.

💡 Key takeaways
Evidence beats prompts. The diagnosis is only as good as the context the agent collects.
Test on a healthy system first. An agent that cries wolf is worse than none.
Keep a human in the loop. The agent is read-only; a person applies the fix.
Design for failure. When the AI call failed during a network blip, the agent still returned the evidence it had collected.

Next: reading pod specs, spotting stuck rollouts, re-checking after a fix, and networking scenarios.

The bigger lesson: an AI agent in operations isn't judged by how confident it sounds, but by whether its evidence is right, its fix actually runs, and it can tell when nothing is wrong.

#Kubernetes #AIAgents #SRE #DevOps #LLM #OpenRouter #NVIDIA #PlatformEngineering
