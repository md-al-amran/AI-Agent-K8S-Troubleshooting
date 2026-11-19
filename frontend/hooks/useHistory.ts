"use client";

import { useQuery } from "@tanstack/react-query";
import { getInsforge } from "@/services/insforge";
import type { HistoryRow } from "@/types/investigation";

export const HISTORY_LIMIT = 10;

export function historyKey(userId: string | undefined) {
  return ["investigations", userId] as const;
}

/** The user's most recent investigations. Row Level Security only returns their own rows. */
export function useHistory(userId: string | undefined) {
  return useQuery({
    queryKey: historyKey(userId),
    enabled: Boolean(userId),
    queryFn: async (): Promise<HistoryRow[]> => {
      const { data, error } = await getInsforge()
        .database.from("investigations")
        .select("id, created_at, status, cluster, title, root_cause, namespace, confidence, diagnosis, error")
        .order("created_at", { ascending: false })
        .limit(HISTORY_LIMIT);
      if (error) throw new Error(error.message);
      return (data ?? []) as HistoryRow[];
    },
  });
}
