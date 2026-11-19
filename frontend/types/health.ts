export type HealthResponse = {
  status: string;
  service: string;
};

export type SystemStatus = "Ready" | "Checking" | "Backend offline";
