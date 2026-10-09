import type {
  ExportedReportItem,
  ExportedReportSession,
  Runner,
  UiHealthCheckNowResponse,
  UiHealthReportsResponse,
  UiHealthSchedule,
} from "../contracts";
import type {FilterProfile, ProfileDefinition, ProfileOptions} from '../filter-profiles';
import type {CurrentCaptcha, RunSchedule, RunScheduleInput, RunTimeZone} from '../run-schedules';

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
export const ACCESS_TOKEN_STORAGE_KEY = "vahanUiAccessToken";
export const AUTH_REQUIRED_EVENT = "vahan:auth-required";
export const AUTH_LOGOUT_EVENT = "vahan:logout";

export interface AuthStatus {
  configured: boolean;
  tokenTtlSeconds: number | null;
  idleTimeoutSeconds?: number;
}

export interface SessionDeadlines {
  expiresAt?: number;
  idleExpiresAt?: number;
}

export interface LoginResponse extends SessionDeadlines {
  accessToken: string;
  tokenType: "Bearer";
  expiresIn: number | null;
  idleTimeoutSeconds?: number;
  username: string;
}

export interface BatchRetryProgress {
  phase: 'PRIMARY' | 'CHECKPOINT' | 'FINAL' | 'DONE';
  checkpointStart: number;
  checkpointEnd: number;
  lastCheckpoint: number;
  finalPassStarted: boolean;
  failedRemaining: number;
  pendingRetries: number;
  complete: boolean;
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
  const token = getAccessToken();
  await request('/api/auth/logout', {method: 'POST'});
  if (getAccessToken() === token) {
    clearAccessToken();
    window.dispatchEvent(new Event(AUTH_LOGOUT_EVENT));
  }
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
    if (response.status === 401 && path !== "/api/auth/login" && getAccessToken() === token) notifyAuthenticationRequired();
    const detail=Array.isArray(body.detail)?body.detail.map((item:{msg?:string})=>item.msg||'Invalid input').join('; '):body.detail;
    throw new ApiError(response.status, (typeof detail==='object'&&detail!==null?JSON.stringify(detail):detail) || `Request failed (${response.status}).`);
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
    if (response.status === 401 && getAccessToken() === token) notifyAuthenticationRequired();
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
  runSchedules: () => request<RunSchedule[]>('/api/run-schedules'),
  createRunSchedule: (input: RunScheduleInput) => request<RunSchedule>('/api/run-schedules', {
    method: 'POST', body: JSON.stringify(input),
  }),
  setRunScheduleTimeZone: (timeZone: RunTimeZone) => request<RunSchedule[]>('/api/run-schedules/time-zone', {
    method: 'POST', body: JSON.stringify({timeZone}),
  }),
  toggleRunSchedule: (id: string, enabled: boolean) => request<RunSchedule>(`/api/run-schedules/${id}`, {
    method: 'PATCH', body: JSON.stringify({enabled}),
  }),
  stopRunSchedule: (id: string) => request<RunSchedule>(`/api/run-schedules/${id}/stop`, {method: 'POST'}),
  pauseRunSchedule: (id: string) => request<RunSchedule>(`/api/run-schedules/${id}/pause`, {method: 'POST'}),
  resumeRunSchedule: (id: string, workerCount: number) => request<RunSchedule>(`/api/run-schedules/${id}/resume`, {method: 'POST', body: JSON.stringify({workerCount})}),
  deleteRunSchedule: (id: string) => request(`/api/run-schedules/${id}`, {method: 'DELETE'}),
  currentCaptchas: () => request<CurrentCaptcha[]>('/api/run-schedules/captchas'),
  filterProfiles:()=>request<FilterProfile[]>('/api/filter-profiles'),
  saveFilterProfile:(name:string,definition:ProfileDefinition,id?:string,revision?:number)=>request<FilterProfile>(
    `/api/filter-profiles${id?`/${id}`:''}`,{method:id?'PUT':'POST',body:JSON.stringify({name,definition,revision})}),
  deleteFilterProfile:(id:string,revision:number)=>request(`/api/filter-profiles/${id}?revision=${revision}`,{method:'DELETE'}),
  filterOptions:(runnerId:string,year:number,context:Record<string,unknown>)=>request<ProfileOptions>('/api/filter-profiles/options',{
    method:'POST',body:JSON.stringify({runnerId,year,context})}),
  filterMakers:(runnerId:string,year:number,search:string)=>request<string[]>('/api/filter-profiles/makers',{
    method:'POST',body:JSON.stringify({runnerId,year,search})}),
  health: () => request<{ status: string }>("/api/health"),
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  login: (username: string, password: string) =>
    request<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  sessionActivity: () => request<SessionDeadlines>("/api/auth/activity", {
    method: "POST",
    body: JSON.stringify({}),
  }),
  currentUser: () => request<{ username: string; role: string } & SessionDeadlines>("/api/auth/me"),
  userState: () => request<Record<string, unknown>>('/api/user-state'),
  putUserState: (key: string, value: unknown, token?: string | null) => request(`/api/user-state/${encodeURIComponent(key)}`, {
    method: 'PUT', body: JSON.stringify({value}), ...(token ? {headers: {Authorization: `Bearer ${token}`}} : {}),
  }),
  logout,
  downloadFile,
  runners: () => request<Runner[]>("/api/runners"),
  uiHealthStatus: () => request<Record<string,unknown>>('/api/ui-health/status'),
  uiPreflight: (runnerIds:string[]) => request<{allowed:boolean;preflightId:string;revision:number;reports:unknown[]}>('/api/ui-health/preflight',{method:'POST',body:JSON.stringify({runnerIds})}),
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
  exportedReports: () => request<ExportedReportItem[]>("/api/jobs/reports"),
  exportedReportSessions: (deleted = false) => request<ExportedReportSession[]>(`/api/jobs/reports/sessions${deleted ? "?deleted=true" : ""}`),
  deleteReportSession: (sessionId: string) => request<{ ok: boolean }>(`/api/jobs/reports/sessions/${sessionId}`, { method: "DELETE" }),
  restoreReportSession: (sessionId: string) => request<{ ok: boolean }>(`/api/jobs/reports/sessions/${sessionId}/restore`, { method: "POST" }),
  verifyReports: (fileNames: string[], sessionIds?: Record<string, string>) => request<{ files: Record<string, number> }>("/api/jobs/reports/verify", {
    method: "POST",
    body: JSON.stringify({ fileNames, ...(sessionIds ? { sessionIds } : {}) }),
  }),
};
