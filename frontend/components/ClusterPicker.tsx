import { ErrorBox } from "@/components/ErrorBox";
import type { ClusterInfo } from "@/types/investigation";

function host(server: string) {
  try {
    return new URL(server).host;
  } catch {
    return server;
  }
}

function Status({ cluster }: { cluster: ClusterInfo }) {
  if (cluster.reachable === true) {
    return <span className="flex items-center gap-1.5 text-xs text-emerald-400"><span className="h-2 w-2 rounded-full bg-emerald-400" />Connected</span>;
  }
  if (cluster.reachable === false) {
    return <span className="flex items-center gap-1.5 text-xs text-red-400"><span className="h-2 w-2 rounded-full bg-red-400" />Unreachable</span>;
  }
  return <span className="text-xs text-slate-500">Not checked</span>;
}

/** Every cluster in the kubeconfig. Click one to choose which cluster to investigate. */
export function ClusterPicker({
  clusters,
  loading,
  error,
  hints,
  selected,
  disabled,
  onSelect,
  onRefresh,
}: {
  clusters: ClusterInfo[];
  loading: boolean;
  error: string | null;
  hints: string[];
  selected: string | null;
  disabled: boolean;
  onSelect: (name: string) => void;
  onRefresh: () => void;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-300">Clusters in your kubeconfig</h2>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading || disabled}
          className="text-xs text-sky-400 hover:underline disabled:opacity-50"
        >
          {loading ? "Checking..." : "Refresh"}
        </button>
      </div>

      {loading && clusters.length === 0 && (
        <p className="text-sm text-slate-500">Looking for clusters and checking each one...</p>
      )}
      {error && <ErrorBox message={error} hints={hints} />}

      <div className="grid gap-2 sm:grid-cols-2">
        {clusters.map((cluster) => {
          const active = cluster.name === selected;
          return (
            <button
              key={cluster.name}
              type="button"
              disabled={disabled}
              onClick={() => onSelect(cluster.name)}
              className={`rounded-lg border p-3 text-left transition disabled:cursor-not-allowed ${
                active ? "border-sky-500 bg-sky-950/30" : "border-slate-800 bg-slate-900 hover:border-slate-600"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="break-all font-mono text-sm text-slate-100">{cluster.name}</span>
                {cluster.current && (
                  <span className="shrink-0 rounded border border-slate-700 px-1.5 text-[10px] uppercase text-slate-400">
                    current
                  </span>
                )}
              </div>
              <p className="mt-1 truncate font-mono text-xs text-slate-500">{host(cluster.server)}</p>
              <div className="mt-2">
                <Status cluster={cluster} />
              </div>
              {cluster.error && <p className="mt-1 text-xs text-red-300/80">{cluster.error}</p>}
            </button>
          );
        })}
      </div>
    </section>
  );
}
