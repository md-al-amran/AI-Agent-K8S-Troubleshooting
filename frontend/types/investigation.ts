// Shapes returned by the FastAPI backend (POST /investigate) and stored in InsForge.

export type Severity = "critical" | "high" | "medium" | "low";

export type IssueDiagnosis = {
  title: string;
  severity: Severity;
  affected_resources: string[];
  root_cause: string;
  explanation: string;
  evidence: string[];
  fix: string;
  kubectl_commands: string[];
  prevention: string;
  confidence: number;
  confidence_level: "high" | "medium" | "low";
  confidence_reasons: string[];
  warnings: string[];
};

export type Diagnosis = IssueDiagnosis & {
  healthy: boolean;
  summary: string;
  other_issues: IssueDiagnosis[];
  model: string | null;
};

export type InvestigationSummary = {
  healthy: boolean;
  problematic_pods: number;
  warning_events: number;
  unhealthy_deployments: number;
  network_issues: number;
  failed_steps: string[];
};

export type InvestigateResponse = {
  status: "success" | "partial" | "error";
  diagnosis: Diagnosis | null;
  investigation: { summary: InvestigationSummary } | null;
  error: string | null;
  investigation_id: string | null;
  cluster: string | null;
  hints: string[];
};

// A cluster (kubeconfig context) from GET /clusters.
export type ClusterInfo = {
  name: string;
  cluster: string;
  server: string;
  namespace: string | null;
  current: boolean;
  reachable: boolean | null;
  error: string | null;
};

export type ClustersResponse = {
  clusters: ClusterInfo[];
  error: string | null;
  hints: string[];
};

export type InvestigationStatus = "running" | "success" | "partial" | "error";

// A row of the `investigations` table in InsForge.
export type HistoryRow = {
  id: string;
  created_at: string;
  status: InvestigationStatus;
  cluster: string | null;
  title: string | null;
  root_cause: string | null;
  namespace: string | null;
  confidence: number | null;
  diagnosis: Diagnosis | null;
  error: string | null;
};

// Realtime "progress" event published by the database trigger on every row change.
export type ProgressEvent = {
  id: string;
  status: InvestigationStatus;
  cluster: string | null;
  current_step: string | null;
  steps: string[];
  title: string | null;
  root_cause: string | null;
  confidence: number | null;
  error: string | null;
};

// Progress steps, in the order the backend runs them.
export const STEPS = [
  { key: "pods", label: "Checking Pods" },
  { key: "logs", label: "Reading Logs" },
  { key: "events", label: "Analyzing Events" },
  { key: "deployments", label: "Inspecting Deployments" },
  { key: "network", label: "Checking Networking" },
  { key: "ai", label: "AI Reasoning" },
] as const;
