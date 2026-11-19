"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getInsforge, insforgeConfigured } from "@/services/insforge";

export type User = { id: string; email: string; name?: string };

type Result = { error?: string; needsVerification?: boolean };

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<Result>;
  signUp: (email: string, password: string, name: string) => Promise<Result>;
  verifyEmail: (email: string, code: string) => Promise<Result>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

type SdkUser = { id: string; email: string; profile?: { name?: string } | null } | null | undefined;

function toUser(user: SdkUser): User | null {
  return user ? { id: user.id, email: user.email, name: user.profile?.name ?? undefined } : null;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // On page load, restore the session (the SDK refreshes it from its cookie if possible).
  useEffect(() => {
    if (!insforgeConfigured) {
      setLoading(false);
      return;
    }
    getInsforge()
      .auth.getCurrentUser()
      .then(({ data }) => setUser(toUser(data?.user)))
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback(async (email: string, password: string): Promise<Result> => {
    const { data, error } = await getInsforge().auth.signInWithPassword({ email, password });
    if (error) {
      // An account that has not confirmed its email yet: send a fresh code and go to the code step.
      if (error.statusCode === 403) {
        await getInsforge().auth.resendVerificationEmail({ email });
        return { needsVerification: true };
      }
      return { error: error.message };
    }
    setUser(toUser(data?.user));
    return {};
  }, []);

  const signUp = useCallback(async (email: string, password: string, name: string): Promise<Result> => {
    const { data, error } = await getInsforge().auth.signUp({ email, password, name: name || undefined });
    if (error) return { error: error.message };
    if (data?.requireEmailVerification) return { needsVerification: true };
    setUser(toUser(data?.user));
    return {};
  }, []);

  const verifyEmail = useCallback(async (email: string, code: string): Promise<Result> => {
    const { data, error } = await getInsforge().auth.verifyEmail({ email, otp: code });
    if (error) return { error: error.message };
    setUser(toUser(data?.user as SdkUser));
    return {};
  }, []);

  const signOut = useCallback(async () => {
    const insforge = getInsforge();
    insforge.realtime.disconnect();
    await insforge.auth.signOut();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signUp, verifyEmail, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
