/** A friendly error: one short message, then a "Please verify" list. Never a stack trace. */
export function ErrorBox({
  message,
  hints = [],
  tone = "error",
  children,
}: {
  message: string;
  hints?: string[];
  tone?: "error" | "warning";
  children?: React.ReactNode;
}) {
  const style =
    tone === "error"
      ? "border-red-900 bg-red-950/40 text-red-300"
      : "border-amber-900 bg-amber-950/40 text-amber-300";

  return (
    <div className={`rounded-lg border p-4 text-sm ${style}`}>
      <p className="font-medium">{message}</p>
      {hints.length > 0 && (
        <>
          <p className="mt-2 text-xs opacity-80">Please verify:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs opacity-90">
            {hints.map((hint) => (
              <li key={hint}>{hint}</li>
            ))}
          </ul>
        </>
      )}
      {children}
    </div>
  );
}
