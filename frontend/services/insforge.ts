import { createClient, type InsForgeClient } from "@insforge/sdk";

// InsForge is used for three things only: sign-in, investigation history, and realtime progress.
const baseUrl = process.env.NEXT_PUBLIC_INSFORGE_BASE_URL ?? "";
const anonKey = process.env.NEXT_PUBLIC_INSFORGE_ANON_KEY ?? "";

export const insforgeConfigured = Boolean(baseUrl && anonKey);

let client: InsForgeClient | null = null;

// Created on first use in the browser, so nothing runs during server rendering.
export function getInsforge(): InsForgeClient {
  if (!client) {
    client = createClient({ baseUrl, anonKey });
  }
  return client;
}

// A valid access token for the signed-in user (refreshed by the SDK when needed).
export async function getAccessToken(): Promise<string | null> {
  return getInsforge().getHttpClient().getValidAccessToken();
}
