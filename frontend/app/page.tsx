"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { ClusterPicker } from "@/components/ClusterPicker";
import { DiagnosisCard } from "@/components/DiagnosisCard";
import { ErrorBox } from "@/components/ErrorBox";
import { Header } from "@/components/Header";
import { HistoryTable } from "@/components/HistoryTable";
import { InvestigateButton } from "@/components/InvestigateButton";
import { ProgressSteps, type StepState } from "@/components/ProgressSteps";
import { useClusters } from "@/hooks/useClusters";
import { historyKey, useHistory } from "@/hooks/useHistory";
import { useRealtimeProgress } from "@/hooks/useRealtimeProgress";
import { ApiError, runInvestigation } from "@/services/api";
import { STEPS, type HistoryRow, type InvestigateResponse, type ProgressEvent } from "@/types/investigation";

function stepStates(
  running: boolean,
  progress: ProgressEvent | null,
  result: InvestigateResponse | undefined,
  failed: boolean,
): Record<string, StepState> {
  const states: Record<string, StepState> = {};
  const done = new Set(progress?.steps ?? []);
  const current = progress?.current_step ?? "pods";

  for (const { key } of STEPS) {
    if (result) {
      // The backend's final answer decides every step.
      const failedSteps = result.investigation?.summary.failed_steps ?? [];
      if (result.status === "error") states[key] = key === "pods" ? "failed" : "pending";
      else if (key === "ai") states[key] = result.status === "success" ? "done" : "failed";
      else states[key] = failedSteps.includes(key) ? "failed" : "done";
    } else if (done.has(key)) {
      states[key] = "done";
    } else if (key === current) {
      states[key] = running ? "running" : failed ? "failed" : "pending";
    } else {
      states[key] = "pending";
    }
  }
  return states;
}

export default function DashboardPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, loading, signOut } = useAuth();
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [selected, setSelected] = useState<HistoryRow | null>(null);
  const [cluster, setCluster] = useState<string | null>(null);
  const history = useHistory(user?.id);
  const clusters = useClusters(Boolean(user));

  const sessionExpired = useCallback(async () => {
    await signOut();
    router.replace("/login?reason=expired");
  }, [signOut, router]);

  // Protected page: send signed-out users to the login screen.
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  // Pre-select the kubeconfig's current cluster once the list arrives.
  useEffect(() => {
    const list = clusters.data?.clusters ?? [];
    if (!cluster && list.length > 0) setCluster((list.find((c) => c.current) ?? list[0]).name);
  }, [clusters.data, cluster]);

  useEffect(() => {
    if (clusters.error instanceof ApiError && clusters.error.unauthorized) sessionExpired();
  }, [clusters.error, sessionExpired]);

  const investigation = useMutation({
    mutationFn: (name: string | null) => runInvestigation(name),
    onMutate: () => {
      setProgress(null);
      setSelected(null);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: historyKey(user?.id) }),
    onError: (error) => {
      if (error instanceof ApiError && error.unauthorized) sessionExpired();
    },
  });

  // Live progress from InsForge realtime (published by a database trigger as the backend works).
  const realtime = useRealtimeProgress(user?.id, (event) => {
    if (investigation.isPending) {
      setProgress((previous) => (!previous || previous.id === event.id ? event : previous));
    }
    // A new row or a finished one: refresh the history table.
    if (event.status !== "running" || event.current_step === "pods") {
      queryClient.invalidateQueries({ queryKey: historyKey(user?.id) });
    }
  });

  if (loading || !user) {
    return <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-500">Loading...</main>;
  }

  const result = investigation.data;
  const investigatedCluster = investigation.variables ?? cluster ?? "cluster";
  const showRun = !selected && !investigation.isIdle;
  const states = stepStates(investigation.isPending, progress, result, investigation.isError);
  const finalLabel =
    result?.status === "success" ? (result.diagnosis?.healthy ? "No Issues Found" : "Root Cause Found") : null;
  const failedSteps = result?.investigation?.summary.failed_steps ?? [];
  const runError = investigation.error instanceof ApiError ? investigation.error : null;

  let progressTitle = `Investigating Kubernetes Cluster ${investigatedCluster}...`;
  if (result?.status === "success") progressTitle = `Investigation complete: ${investigatedCluster}`;
  else if (result || investigation.isError) progressTitle = `Investigation stopped: ${investigatedCluster}`;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header
        email={user.email}
        realtime={realtime}
        onSignOut={async () => {
          await signOut();
          router.replace("/login");
        }}
      />

      <main className="mx-auto max-w-4xl space-y-8 px-4 py-8">
        <ClusterPicker
          clusters={clusters.data?.clusters ?? []}
          loading={clusters.isFetching}
          error={clusters.data?.error ?? (clusters.error && !runError ? clusters.error.message : null)}
          hints={clusters.data?.hints ?? (clusters.error instanceof ApiError ? clusters.error.hints : [])}
          selected={cluster}
          disabled={investigation.isPending}
          onSelect={setCluster}
          onRefresh={() => clusters.refetch()}
        />

        <section className="flex flex-col items-center gap-2 text-center">
          <InvestigateButton
            onClick={() => investigation.mutate(cluster)}
            loading={investigation.isPending}
            disabled={!cluster}
          />
          <p className="text-xs text-slate-500">
            {cluster ? (
              <>
                Target: <span className="font-mono text-slate-300">{cluster}</span>
              </>
            ) : (
              "Pick a cluster above"
            )}
          </p>
        </section>

        {showRun && (
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-300">
              {investigation.isPending && (
                <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-sky-400 border-t-transparent" />
              )}
              {progressTitle}
            </h2>
            <ProgressSteps states={states} finalLabel={finalLabel} />
          </section>
        )}

        {/* Result of the investigation that just ran */}
        {showRun && investigation.isError && (
          <ErrorBox message={investigation.error.message} hints={runError?.hints ?? []} />
        )}
        {showRun && result && (
          <section className="space-y-3">
            <h2 className="text-sm font-medium text-slate-300">Diagnosis</h2>
            {result.error && (
              <ErrorBox message={result.error} hints={result.hints} tone={result.status === "error" ? "error" : "warning"}>
                {result.investigation && (
                  <p className="mt-2 text-xs opacity-80">
                    Evidence collected: {result.investigation.summary.problematic_pods} problem pod(s),{" "}
                    {result.investigation.summary.warning_events} warning event(s),{" "}
                    {result.investigation.summary.unhealthy_deployments} unhealthy deployment(s),{" "}
                    {result.investigation.summary.network_issues} network issue(s).
                  </p>
                )}
              </ErrorBox>
            )}
            {failedSteps.length > 0 && (
              <ErrorBox
                tone="warning"
                message={`Some checks could not run: ${failedSteps.join(", ")}. The diagnosis may be incomplete.`}
                hints={["Your kubeconfig user may lack read permission for these resources", "Check the backend logs for the exact kubectl error"]}
              />
            )}
            {result.diagnosis && <DiagnosisCard diagnosis={result.diagnosis} />}
          </section>
        )}

        {/* A past investigation picked from the history table */}
        {selected && (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-slate-300">
                {selected.cluster ?? "Cluster"} · {new Date(selected.created_at).toLocaleString()}
              </h2>
              <button type="button" className="text-xs text-sky-400 hover:underline" onClick={() => setSelected(null)}>
                Close
              </button>
            </div>
            {selected.error && <ErrorBox message={selected.error} tone={selected.status === "error" ? "error" : "warning"} />}
            {selected.diagnosis ? (
              <DiagnosisCard diagnosis={selected.diagnosis} />
            ) : (
              !selected.error && <p className="text-sm text-slate-500">This investigation is still running.</p>
            )}
          </section>
        )}

        <section className="space-y-3">
          <h2 className="text-sm font-medium text-slate-300">Recent Investigations</h2>
          <HistoryTable
            rows={history.data ?? []}
            loading={history.isLoading}
            error={history.error?.message ?? null}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
          />
        </section>
      </main>
    </div>
  );
}
