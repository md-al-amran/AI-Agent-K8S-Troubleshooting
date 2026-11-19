"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { insforgeConfigured } from "@/services/insforge";

type Mode = "signIn" | "signUp" | "verify";

const inputClass =
  "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-sky-500 focus:outline-none";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, signIn, signUp, verifyEmail } = useAuth();
  const [mode, setMode] = useState<Mode>("signIn");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Sent here because the session ran out (see the dashboard).
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("reason") === "expired") {
      setNotice("Your session has expired. Please sign in again.");
    }
  }, []);

  // Already signed in: go to the dashboard.
  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);

    const result =
      mode === "signIn"
        ? await signIn(email, password)
        : mode === "signUp"
          ? await signUp(email, password, name)
          : await verifyEmail(email, code);

    setBusy(false);
    if (result.needsVerification) {
      setMode("verify");
      setNotice(`We sent a 6-digit code to ${email}. Enter it below to confirm your email.`);
    } else if (result.error) {
      setError(result.error);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setNotice(null);
  }

  const title = mode === "signIn" ? "Sign in" : mode === "signUp" ? "Create an account" : "Confirm your email";
  const button = mode === "signIn" ? "Sign in" : mode === "signUp" ? "Create account" : "Confirm";

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">AI Kubernetes Agent</h1>
          <p className="mt-2 text-sm text-slate-400">Troubleshoot Kubernetes with AI</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-lg font-medium">{title}</h2>

          {!insforgeConfigured && (
            <p className="rounded-md bg-amber-950 px-3 py-2 text-sm text-amber-300">
              InsForge is not configured. Set NEXT_PUBLIC_INSFORGE_BASE_URL and NEXT_PUBLIC_INSFORGE_ANON_KEY.
            </p>
          )}
          {notice && <p className="rounded-md bg-sky-950 px-3 py-2 text-sm text-sky-300">{notice}</p>}
          {error && <p className="rounded-md bg-red-950 px-3 py-2 text-sm text-red-300">{error}</p>}

          {mode === "signUp" && (
            <input className={inputClass} placeholder="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
          )}
          {mode !== "verify" && (
            <>
              <input
                className={inputClass}
                type="email"
                placeholder="Email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <input
                className={inputClass}
                type="password"
                placeholder="Password"
                autoComplete={mode === "signUp" ? "new-password" : "current-password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </>
          )}
          {mode === "verify" && (
            <input
              className={`${inputClass} tracking-widest`}
              placeholder="6-digit code"
              inputMode="numeric"
              maxLength={6}
              required
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            />
          )}

          <button
            type="submit"
            disabled={busy || !insforgeConfigured}
            className="w-full rounded-md bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Please wait..." : button}
          </button>

          <p className="text-center text-sm text-slate-400">
            {mode === "signIn" ? (
              <>
                No account?{" "}
                <button type="button" className="text-sky-400 hover:underline" onClick={() => switchMode("signUp")}>
                  Create one
                </button>
              </>
            ) : (
              <>
                {mode === "verify" ? "Wrong email? " : "Have an account? "}
                <button type="button" className="text-sky-400 hover:underline" onClick={() => switchMode("signIn")}>
                  Back to sign in
                </button>
              </>
            )}
          </p>
        </form>
      </div>
    </main>
  );
}
