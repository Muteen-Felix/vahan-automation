import type {
  ExportedReportItem,
  ExportedReportSession,
  Job,
  MakerUpdateRun,
  Runner,
  UiHealthCheckNowResponse,
  UiHealthReportsResponse,
  UiHealthSchedule,
  VahanFilters,
} from "../contracts";

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
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

async function logout() {
  await request('/api/auth/logout', {method: 'POST'});
  clearAccessToken();
  window.dispatchEvent(new Event(AUTH_LOGOUT_EVENT));
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
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

async function downloadFile(path: string, fileName?: string): Promise<void> {
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
  const disposition = response.headers.get('Content-Disposition') || '';
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  let serverName = 'report.xlsx';
  if (encodedName) {try {serverName = decodeURIComponent(encodedName);} catch { /* Fall back to a safe name. */ }}
  anchor.download = fileName || serverName;
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
  currentUser: () => request<{ username: string; role: string }>("/api/auth/me"),
  userState: () => request<Record<string, unknown>>('/api/user-state'),
  putUserState: (key: string, value: unknown, token?: string | null) => request(`/api/user-state/${encodeURIComponent(key)}`, {
    method: 'PUT', body: JSON.stringify({value}), ...(token ? {headers: {Authorization: `Bearer ${token}`}} : {}),
  }),
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
  createJob: (runnerId: string, filters: VahanFilters, scenarioName?: string, sessionId?: string, retryOfJobId?: string,
    update?: {updateKind: "GLOBAL" | "DISCOVER" | "REFRESH"; updateRunId?: string; updateTaskId?: string}) =>
    request<Job>("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ runnerId, filters, scenarioName, sessionId, retryOfJobId, ...update }),
    }),
  makerUpdates: (year: number) => request<MakerUpdateRun[]>(`/api/maker-updates?year=${year}`),
  makerUpdate: (id: string) => request<MakerUpdateRun>(`/api/maker-updates/${id}`),
  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),
  cancelJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  exportedReports: () => request<ExportedReportItem[]>("/api/jobs/reports"),
  exportedReportSessions: (deleted = false) => request<ExportedReportSession[]>(`/api/jobs/reports/sessions${deleted ? "?deleted=true" : ""}`),
  deleteReportSession: (sessionId: string) => request<{ ok: boolean }>(`/api/jobs/reports/sessions/${sessionId}`, { method: "DELETE" }),
  restoreReportSession: (sessionId: string) => request<{ ok: boolean }>(`/api/jobs/reports/sessions/${sessionId}/restore`, { method: "POST" }),
  verifyReports: (fileNames: string[], sessionIds?: Record<string, string>) => request<{ files: Record<string, number> }>("/api/jobs/reports/verify", {
    method: "POST",
    body: JSON.stringify({ fileNames, ...(sessionIds ? { sessionIds } : {}) }),
  }),
};
