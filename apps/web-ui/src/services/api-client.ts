import type {
  ExportedReportItem,
  ExportedReportSession,
  Job,
  Runner,
  UiHealthCheckNowResponse,
  UiHealthReportsResponse,
  UiHealthSchedule,
  VahanFilters,
} from "../contracts";

export const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
export const ACCESS_TOKEN_STORAGE_KEY = "vahanUiAccessToken";
export const AUTH_REQUIRED_EVENT = "vahan:auth-required";
export const AUTH_LOGOUT_EVENT = "vahan:logout";

export interface AuthStatus {
  configured: boolean;
  tokenTtlSeconds: number | null;
}

export interface LoginResponse {
  accessToken: string;
  tokenType: "Bearer";
  expiresIn: number | null;
  username: string;
}

export function getAccessToken(): string | null {
  try {
    const persistentToken = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    if (persistentToken) return persistentToken;
    const previousSessionToken = window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    if (previousSessionToken) {
      try {
        window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, previousSessionToken);
        window.sessionStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
      } catch {
        // Continue using the previous session token when persistent storage is unavailable.
      }
    }
    return previousSessionToken;
  } catch {
    return null;
  }
}

function notifyAuthenticationRequired() {
  window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
}

export function clearAccessToken() {
  try {
    window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    // Continue clearing the legacy tab-scoped token below.
  }
  try {
    window.sessionStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    // The UI remains usable if browser storage is disabled; the next request will require login.
  }
}

function logout() {
  clearAccessToken();
  window.dispatchEvent(new Event(AUTH_LOGOUT_EVENT));
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && path !== "/api/auth/login") notifyAuthenticationRequired();
    throw new ApiError(response.status, body.detail || `Request failed (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

async function downloadFile(path: string, fileName: string): Promise<void> {
  const token = getAccessToken();
  const response = await fetch(`${API_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) notifyAuthenticationRequired();
    throw new Error(body.detail || `Could not download the file (${response.status}).`);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = fileName;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  login: (username: string, password: string) =>
    request<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  renewSession: () => request<LoginResponse>("/api/auth/renew", {
    method: "POST",
    body: JSON.stringify({}),
  }),
  currentUser: () => request<{ username: string }>("/api/auth/me"),
  logout,
  downloadFile,
  runners: () => request<Runner[]>("/api/runners"),
  uiHealthSchedule: () => request<UiHealthSchedule>("/api/ui-health/schedule"),
  updateUiHealthSchedule: (intervalDays: number) =>
    request<UiHealthSchedule>("/api/ui-health/schedule", {
      method: "PUT",
      body: JSON.stringify({ intervalDays }),
    }),
  runUiHealthCheckNow: (runnerId?: string) =>
    request<UiHealthCheckNowResponse>("/api/ui-health/run-now", {
      method: "POST",
      body: JSON.stringify(runnerId ? { runnerId } : {}),
    }),
  uiHealthReports: (date?: string) => request<UiHealthReportsResponse>(
    `/api/ui-health/reports${date ? `?date=${encodeURIComponent(date)}` : ""}`,
  ),
  createJob: (runnerId: string, filters: VahanFilters, scenarioName?: string, sessionId?: string) =>
    request<Job>("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ runnerId, filters, scenarioName, ...(sessionId ? { sessionId } : {}) }),
    }),
  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),
  cancelJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  exportedReports: () => request<ExportedReportItem[]>("/api/jobs/reports"),
  exportedReportSessions: () => request<ExportedReportSession[]>("/api/jobs/reports/sessions"),
  verifyReports: (fileNames: string[], sessionIds?: Record<string, string>) => request<{ files: Record<string, number> }>("/api/jobs/reports/verify", {
    method: "POST",
    body: JSON.stringify({ fileNames, ...(sessionIds ? { sessionIds } : {}) }),
  }),
};
