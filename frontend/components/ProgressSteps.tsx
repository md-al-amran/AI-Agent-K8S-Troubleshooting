import { STEPS } from "@/types/investigation";

export type StepState = "pending" | "running" | "done" | "failed";

const icon: Record<StepState, React.ReactNode> = {
  done: <span className="text-emerald-400">✓</span>,
  failed: <span className="text-red-400">✗</span>,
  pending: <span className="text-slate-600">○</span>,
  running: (
    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-sky-400 border-t-transparent" />
  ),
};

const text: Record<StepState, string> = {
  done: "text-slate-200",
  failed: "text-red-300",
  pending: "text-slate-500",
  running: "text-sky-300",
};

/** The checklist of investigation steps, plus a final "Root Cause Found" line. */
export function ProgressSteps({
  states,
  finalLabel,
}: {
  states: Record<string, StepState>;
  finalLabel: string | null;
}) {
  return (
    <ul className="space-y-2 text-sm">
      {STEPS.map((step) => {
        const state = states[step.key] ?? "pending";
        return (
          <li key={step.key} className="flex items-center gap-3">
            <span className="flex w-4 justify-center">{icon[state]}</span>
            <span className={text[state]}>{step.label}</span>
          </li>
        );
      })}
      {finalLabel && (
        <li className="flex items-center gap-3 font-medium">
          <span className="flex w-4 justify-center">{icon.done}</span>
          <span className="text-emerald-300">{finalLabel}</span>
        </li>
      )}
    </ul>
  );
}
