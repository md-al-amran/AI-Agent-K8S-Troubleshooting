"use client";

import { useSystemStatus } from "@/hooks/useSystemStatus";
import type { RealtimeStatus } from "@/hooks/useRealtimeProgress";

const dot: Record<string, string> = {
  Ready: "bg-emerald-400",
  Checking: "bg-slate-500",
  "Backend offline": "bg-red-400",
};

export function Header({
  email,
  realtime,
  onSignOut,
}: {
  email: string;
  realtime: RealtimeStatus;
  onSignOut: () => void;
}) {
  const { status } = useSystemStatus();

  return (
    <header className="border-b border-slate-800">
      <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">AI Kubernetes Agent</h1>
          <p className="flex items-center gap-3 text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${dot[status]}`} />
              System Status: {status}
            </span>
            <span>Live updates: {realtime === "live" ? "on" : realtime === "connecting" ? "connecting" : "off"}</span>
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-slate-400">{email}</span>
          <button
            type="button"
            onClick={onSignOut}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 transition hover:bg-slate-800"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
