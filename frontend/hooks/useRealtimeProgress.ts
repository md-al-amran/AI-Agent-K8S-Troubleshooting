"use client";

import { useEffect, useRef, useState } from "react";
import { getInsforge } from "@/services/insforge";
import type { ProgressEvent } from "@/types/investigation";

export type RealtimeStatus = "connecting" | "live" | "offline";

/**
 * Listen to the signed-in user's realtime channel `investigations:<userId>`.
 * A database trigger in InsForge publishes a "progress" event every time the
 * backend updates an investigation row.
 */
export function useRealtimeProgress(userId: string | undefined, onEvent: (event: ProgressEvent) => void) {
  const [status, setStatus] = useState<RealtimeStatus>("connecting");
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!userId) return;
    const realtime = getInsforge().realtime;
    const channel = `investigations:${userId}`;
    const handler = (payload: ProgressEvent) => onEventRef.current(payload);
    let cancelled = false;

    realtime.on<ProgressEvent>("progress", handler);
    (async () => {
      try {
        await realtime.connect();
        const response = await realtime.subscribe(channel);
        if (!cancelled) setStatus(response.ok ? "live" : "offline");
      } catch {
        if (!cancelled) setStatus("offline"); // the dashboard still works, just without live steps
      }
    })();

    return () => {
      cancelled = true;
      realtime.off<ProgressEvent>("progress", handler);
      realtime.unsubscribe(channel);
    };
  }, [userId]);

  return status;
}
