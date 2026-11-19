"use client";

export function InvestigateButton({
  onClick,
  loading = false,
  disabled = false,
}: {
  onClick?: () => void;
  loading?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading || disabled}
      className="rounded-md bg-sky-500 px-6 py-3 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {loading ? "Investigating..." : "Investigate Cluster"}
    </button>
  );
}
