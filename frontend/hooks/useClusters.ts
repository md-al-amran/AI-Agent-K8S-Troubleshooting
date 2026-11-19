"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchClusters } from "@/services/api";

/** Clusters (kubeconfig contexts) the backend can see, each with a reachability check. */
export function useClusters(enabled: boolean) {
  return useQuery({
    queryKey: ["clusters"],
    queryFn: fetchClusters,
    enabled,
    staleTime: 60_000,
    retry: false,
  });
}
