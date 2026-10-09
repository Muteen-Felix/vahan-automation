import type {
  ExportedReportItem,
  ExportedReportSession,
  Runner,
  UiHealthCheckNowResponse,
  UiHealthReportsResponse,
  UiHealthSchedule,
} from "../contracts";
import type {FilterProfile, ProfileDefinition, ProfileOptions} from '../filter-profiles';
import type {CurrentCaptcha, RunSchedule, RunScheduleInput} from '../run-schedules';

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
export const SESSION_MARKER_STORAGE_KEY = "vahanUiSessionMarker";
let csrf = '';
let bearerAccessToken = '';
// Keep credentials out of persistent browser storage. Cookie sessions stay
// HttpOnly; APIs that return a Bearer token use it only for this page session.
try { localStorage.removeItem('vahanUiAccessToken'); sessionStorage.removeItem('vahanUiAccessToken'); } catch { /* Storage may be disabled. */ }
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
  accessToken: string | null;
  sessionMarker?: string;
  csrfToken?: string;
  mfaSetupToken?: string;
  tokenType: "Bearer" | "Cookie";
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

export function getSessionMarker(): string | null {
  try {
    return window.localStorage.getItem(SESSION_MARKER_STORAGE_KEY);
  } catch {
    return null;
  }
}

function notifyAuthenticationRequired() {
  window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
}

export function clearSessionMarker() {
  csrf = '';
  bearerAccessToken = '';
  try {
    window.localStorage.removeItem(SESSION_MARKER_STORAGE_KEY);
  } catch {
    // Continue clearing the legacy tab-scoped token below.
  }
  try {
    window.sessionStorage.removeItem(SESSION_MARKER_STORAGE_KEY);
  } catch {
    // The UI remains usable if browser storage is disabled; the next request will require login.
  }
}

export function acceptLoginSession(result: LoginResponse) {
  csrf = result.csrfToken || '';
  bearerAccessToken = result.tokenType === 'Bearer' ? result.accessToken || '' : '';
  localStorage.setItem(SESSION_MARKER_STORAGE_KEY, result.sessionMarker || crypto.randomUUID());
}

export function getBearerAccessToken() {
  return bearerAccessToken || null;
}

export function csrfHeaders(): Record<string, string> {
  return csrf ? {'X-CSRF-Token': csrf} : {};
}

async function logout() {
  const token = getSessionMarker();
  await request('/api/auth/logout', {method: 'POST'});
  if (getSessionMarker() === token) {
    clearSessionMarker();
    window.dispatchEvent(new Event(AUTH_LOGOUT_EVENT));
  }
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getSessionMarker();
  const authorization: Record<string, string> = path === '/api/auth/login' || !bearerAccessToken
    ? {}
    : {Authorization: `Bearer ${bearerAccessToken}`};
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      "Content-Type": "application/json",
      ...csrfHeaders(),
      ...authorization,
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && path !== "/api/auth/login" && getSessionMarker() === token) notifyAuthenticationRequired();
    const detail=Array.isArray(body.detail)?body.detail.map((item:{msg?:string})=>item.msg||'Invalid input').join('; '):body.detail;
    throw new ApiError(response.status, (typeof detail==='object'&&detail!==null?JSON.stringify(detail):detail) || `Request failed (${response.status}).`);
  }
  const result = await response.json();
  if (typeof result.csrfToken === 'string') csrf = result.csrfToken;
  return result as T;
}

async function downloadFile(path: string, fileName?: string): Promise<void> {
  const token = getSessionMarker();
  const authorization: Record<string, string> = bearerAccessToken ? {Authorization: `Bearer ${bearerAccessToken}`} : {};
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: authorization,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && getSessionMarker() === token) notifyAuthenticationRequired();
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
      body: JSON.stringify({ username, password, browserSession: true }),
    }),
  sessionActivity: () => request<SessionDeadlines>("/api/auth/activity", {
    method: "POST",
    body: JSON.stringify({}),
  }),
  currentUser: () => request<{ username: string; role: string; tenantId?: string; csrfToken?: string } & SessionDeadlines>("/api/auth/me"),
  userState: () => request<Record<string, unknown>>('/api/user-state'),
  putUserState: (key: string, value: unknown, token?: string | null) => {
    if (token && token !== getSessionMarker()) return Promise.reject(new Error('The active session changed.'));
    return request(`/api/user-state/${encodeURIComponent(key)}`, {method: 'PUT', body: JSON.stringify({value})});
  },
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
  exportedReportSessions: (deleted = false, offset = 0) => request<ExportedReportSession[]>(`/api/jobs/reports/sessions?deleted=${deleted}&offset=${offset}&limit=100`),
  exportedReportSession: (sessionId: string, offset = 0) => request<ExportedReportSession>(`/api/jobs/reports/sessions/${encodeURIComponent(sessionId)}?offset=${offset}&limit=100`),
  deleteReportSession: (sessionId: string) => request<{ ok: boolean }>(`/api/jobs/reports/sessions/${sessionId}`, { method: "DELETE" }),
  restoreReportSession: (sessionId: string) => request<{ ok: boolean }>(`/api/jobs/reports/sessions/${sessionId}/restore`, { method: "POST" }),
  verifyReports: (fileNames: string[], sessionIds?: Record<string, string>) => request<{ files: Record<string, number> }>("/api/jobs/reports/verify", {
    method: "POST",
    body: JSON.stringify({ fileNames, ...(sessionIds ? { sessionIds } : {}) }),
  }),
};
