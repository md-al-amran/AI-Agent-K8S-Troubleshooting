"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import type { HealthResponse, SystemStatus } from "@/types/health";

/** Backend health from GET /health, checked every 30 seconds. */
export function useSystemStatus(): { status: SystemStatus } {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["health"],
    queryFn: async () => (await api.get<HealthResponse>("/health", { timeout: 5000 })).data,
    refetchInterval: 30_000,
    retry: false,
  });

  if (isLoading) return { status: "Checking" };
  if (isError || data?.status !== "healthy") return { status: "Backend offline" };
  return { status: "Ready" };
}
