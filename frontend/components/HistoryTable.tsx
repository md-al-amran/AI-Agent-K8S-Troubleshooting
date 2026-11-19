import type { HistoryRow, InvestigationStatus } from "@/types/investigation";

const statusStyle: Record<InvestigationStatus, string> = {
  running: "text-sky-300",
  success: "text-emerald-400",
  partial: "text-amber-400",
  error: "text-red-400",
};

const statusLabel: Record<InvestigationStatus, string> = {
  running: "Running",
  success: "Diagnosed",
  partial: "No AI result",
  error: "Failed",
};

function formatTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function HistoryTable({
  rows,
  loading,
  error,
  selectedId,
  onSelect,
}: {
  rows: HistoryRow[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (row: HistoryRow) => void;
}) {
  if (loading) return <p className="text-sm text-slate-500">Loading history...</p>;
  if (error) return <p className="text-sm text-red-400">Could not load history: {error}</p>;
  if (rows.length === 0) return <p className="text-sm text-slate-500">No investigations yet.</p>;

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-2 font-medium">Time</th>
            <th className="px-4 py-2 font-medium">Cluster</th>
            <th className="px-4 py-2 font-medium">Issue</th>
            <th className="px-4 py-2 font-medium">Namespace</th>
            <th className="px-4 py-2 font-medium">Confidence</th>
            <th className="px-4 py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => onSelect(row)}
              className={`cursor-pointer transition hover:bg-slate-900 ${row.id === selectedId ? "bg-slate-900" : ""}`}
            >
              <td className="whitespace-nowrap px-4 py-2 text-slate-400">{formatTime(row.created_at)}</td>
              <td className="max-w-[10rem] truncate px-4 py-2 font-mono text-xs text-slate-400" title={row.cluster ?? ""}>
                {row.cluster ?? "—"}
              </td>
              <td className="max-w-xs truncate px-4 py-2 text-slate-200" title={row.root_cause ?? row.error ?? ""}>
                {row.title ?? (row.status === "running" ? "Investigating..." : "—")}
              </td>
              <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-slate-400">{row.namespace ?? "—"}</td>
              <td className="px-4 py-2 text-slate-300">{row.confidence != null ? `${row.confidence}%` : "—"}</td>
              <td className={`whitespace-nowrap px-4 py-2 ${statusStyle[row.status]}`}>{statusLabel[row.status]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
