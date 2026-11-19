import axios, { AxiosError } from "axios";
import type { ClustersResponse, InvestigateResponse } from "@/types/investigation";
import { getAccessToken } from "@/services/insforge";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// The AI step can take a while (model call plus retries), so allow up to 5 minutes.
const INVESTIGATE_TIMEOUT_MS = 5 * 60 * 1000;
// Listing clusters checks each one; an unreachable cluster takes a few seconds to time out.
const CLUSTERS_TIMEOUT_MS = 30 * 1000;

export const api = axios.create({ baseURL: API_BASE_URL });

// Thrown for every failure the UI should show to the user: a short message plus things to check.
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly hints: string[] = [],
    public readonly unauthorized = false,
  ) {
    super(message);
  }
}

async function authHeaders() {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError("Your session has expired. Please sign in again.", [], true);
  }
  return { Authorization: `Bearer ${token}` };
}

export async function fetchClusters(): Promise<ClustersResponse> {
  try {
    const { data } = await api.get<ClustersResponse>("/clusters", {
      headers: await authHeaders(),
      timeout: CLUSTERS_TIMEOUT_MS,
    });
    return data;
  } catch (error) {
    throw toApiError(error, "Loading clusters took too long.");
  }
}

export async function runInvestigation(cluster: string | null): Promise<InvestigateResponse> {
  try {
    const { data } = await api.post<InvestigateResponse>(
      "/investigate",
      { cluster },
      { headers: await authHeaders(), timeout: INVESTIGATE_TIMEOUT_MS },
    );
    if (!data || !data.status) {
      throw new ApiError("The backend returned an empty response.", ["Investigate again", "Check the backend logs"]);
    }
    return data;
  } catch (error) {
    throw toApiError(error, "The investigation took too long and was stopped.");
  }
}

function toApiError(error: unknown, timeoutMessage: string): ApiError {
  if (error instanceof ApiError) return error;
  if (!(error instanceof AxiosError)) return new ApiError("Something went wrong. Please try again.");

  if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
    return new ApiError(timeoutMessage, [
      "Try again; the AI model may have been slow",
      "If the cluster is far away or slow, check that `kubectl get pods -A` responds quickly",
    ]);
  }
  if (!error.response) {
    return new ApiError(`Cannot reach the backend at ${API_BASE_URL}.`, [
      "Is the backend running? (`docker compose ps` or `uvicorn app.main:app`)",
      "Check NEXT_PUBLIC_API_BASE_URL in the frontend settings",
    ]);
  }

  // The backend answers errors as { error, hints } (investigate) or { detail } (auth).
  const body = error.response.data as { detail?: string; error?: string; hints?: string[] } | undefined;
  const message = body?.error ?? body?.detail;
  if (error.response.status === 401) {
    return new ApiError(message ?? "Please sign in again.", [], true);
  }
  return new ApiError(message ?? `The backend returned HTTP ${error.response.status}.`, body?.hints ?? []);
}
