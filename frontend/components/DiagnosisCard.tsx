"use client";

import { useState } from "react";
import type { Diagnosis, IssueDiagnosis } from "@/types/investigation";

const severityStyle: Record<string, string> = {
  critical: "bg-red-950 text-red-300 border-red-900",
  high: "bg-orange-950 text-orange-300 border-orange-900",
  medium: "bg-amber-950 text-amber-300 border-amber-900",
  low: "bg-slate-800 text-slate-300 border-slate-700",
};

const confidenceStyle: Record<string, string> = {
  high: "text-emerald-400",
  medium: "text-amber-400",
  low: "text-red-400",
};

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</h4>
      <div className="mt-1 text-sm leading-relaxed text-slate-200">{children}</div>
    </div>
  );
}

function CommandBlock({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard not available (for example over plain http); the text can still be selected
    }
  }

  return (
    <div className="group flex items-start gap-2 rounded-md bg-slate-950 px-3 py-2 font-mono text-xs text-emerald-300">
      <code className="flex-1 whitespace-pre-wrap break-all">{command}</code>
      <button type="button" onClick={copy} className="shrink-0 text-slate-500 hover:text-slate-200">
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function IssueDetails({ issue }: { issue: IssueDiagnosis }) {
  return (
    <div className="space-y-4">
      <Section label="Root Cause">{issue.root_cause}</Section>
      {issue.explanation && <Section label="Explanation">{issue.explanation}</Section>}
      {issue.fix && <Section label="Suggested Fix">{issue.fix}</Section>}

      {issue.kubectl_commands.length > 0 && (
        <Section label="kubectl Commands">
          <div className="space-y-2">
            {issue.kubectl_commands.map((command) => (
              <CommandBlock key={command} command={command} />
            ))}
          </div>
        </Section>
      )}

      {issue.warnings.length > 0 && (
        <ul className="space-y-1 rounded-md border border-amber-900 bg-amber-950 px-3 py-2 text-xs text-amber-300">
          {issue.warnings.map((warning) => (
            <li key={warning}>⚠ {warning}</li>
          ))}
        </ul>
      )}

      {issue.prevention && <Section label="Prevention">{issue.prevention}</Section>}

      <Section label="Confidence">
        <span className={`text-lg font-semibold ${confidenceStyle[issue.confidence_level]}`}>{issue.confidence}%</span>
        <span className="ml-2 text-xs text-slate-500">{issue.confidence_level}</span>
        {issue.confidence_reasons.length > 0 && (
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-400">
            {issue.confidence_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

export function DiagnosisCard({ diagnosis }: { diagnosis: Diagnosis }) {
  if (diagnosis.healthy) {
    return (
      <div className="rounded-lg border border-emerald-900 bg-emerald-950/40 p-5">
        <h3 className="font-medium text-emerald-300">✓ No critical Kubernetes issues detected.</h3>
        <p className="mt-1 text-sm text-slate-300">Cluster appears healthy.</p>
        {diagnosis.summary && !diagnosis.summary.startsWith("No critical") && (
          <p className="mt-2 text-xs text-slate-400">{diagnosis.summary}</p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="font-medium text-slate-100">{diagnosis.title || "Diagnosis"}</h3>
            {diagnosis.affected_resources.length > 0 && (
              <p className="mt-0.5 font-mono text-xs text-slate-500">{diagnosis.affected_resources.join(", ")}</p>
            )}
          </div>
          <span className={`rounded border px-2 py-0.5 text-xs font-medium ${severityStyle[diagnosis.severity]}`}>
            {diagnosis.severity}
          </span>
        </div>
        <IssueDetails issue={diagnosis} />
      </div>

      {diagnosis.other_issues.length > 0 && (
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h3 className="mb-3 text-sm font-medium text-slate-300">Other issues ({diagnosis.other_issues.length})</h3>
          <div className="space-y-2">
            {diagnosis.other_issues.map((issue, index) => (
              <details key={`${issue.title}-${index}`} className="rounded-md border border-slate-800 bg-slate-950/50">
                <summary className="flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-sm">
                  <span className="text-slate-200">{issue.title || issue.root_cause}</span>
                  <span className="shrink-0 text-xs text-slate-500">
                    {issue.severity} · {issue.confidence}%
                  </span>
                </summary>
                <div className="border-t border-slate-800 p-3">
                  <IssueDetails issue={issue} />
                </div>
              </details>
            ))}
          </div>
        </div>
      )}

      {diagnosis.model && <p className="text-xs text-slate-600">Diagnosed by {diagnosis.model}</p>}
    </div>
  );
}
