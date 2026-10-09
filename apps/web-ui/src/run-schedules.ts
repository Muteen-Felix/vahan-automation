import {persistentState} from './services/persistent-state';

export interface RunSchedule {
  id: string;
  profileId: string;
  profileName: string;
  profileRevision: number;
  year: number;
  workerCount: number;
  startsAt: string;
  nextRunAt: string | null;
  repeat: 'once' | 'daily' | 'monthly';
  timeZone: RunTimeZone;
  enabled: boolean;
  status: 'WAITING' | 'PREPARING' | 'RUNNING' | 'PAUSING' | 'PAUSED' | 'RESUMING' | 'COMPLETED' | 'COMPLETED_WITH_ERRORS' | 'ERROR' | 'STOPPED';
  sessionId: string | null;
  lastSessionId: string | null;
  lastRunAt?: string | null;
  lastFinishedAt?: string | null;
  canResume?: boolean;
  executionEpoch?: number;
  activeElapsedMs?: number;
  activeSegmentStartedAt?: string | null;
  networkPaused?: boolean;
  updatedAt?: string;
  retryAfter?: string | null;
  operation?: {stage: string; detail: string; startedAt: string; progressAt: string; heartbeatAt: string; error: string | null} | null;
  diagnostics?: {checkedAt: string; heartbeatAgeSeconds: number | null; stageAgeSeconds: number | null; warning: string | null;
    workers: {id: string; selected: boolean; connected: boolean; browserReady?: boolean; optionsBusy?: boolean; reachable?: boolean;
      heartbeatAgeSeconds: number | null; jobId: string | null; status: string; case: string | null; error: string | null; jobAgeSeconds: number | null}[]};
  message: string;
  total: number;
  done: number;
  withData: number;
  noData: number;
  failed: number;
  retryProgress?: import('./services/api-client').BatchRetryProgress | null;
}

export function canResumeSchedule(value: RunSchedule) {
  if(value.networkPaused) return false;
  return value.canResume ?? (value.status === 'PAUSED' && Boolean(value.sessionId)
    || value.status === 'STOPPED' && Boolean(value.lastSessionId) && value.done < value.total);
}

export interface RunScheduleInput {
  profileId: string;
  year: number;
  workerCount: number;
  startsAt: string;
  repeat: 'once' | 'daily' | 'monthly';
  timeZone: RunTimeZone;
}

export interface CurrentCaptcha {
  jobId: string;
  runnerId: string;
  captchaId: string;
  scenarioName: string | null;
}

export const RUN_TIME_ZONE = 'Asia/Ho_Chi_Minh' as const;
export const INDIA_TIME_ZONE = 'Asia/Kolkata' as const;
export const RUN_TIME_ZONE_STORAGE_KEY = 'vahanScheduleTimeZoneV1';
export type RunTimeZone = typeof RUN_TIME_ZONE | typeof INDIA_TIME_ZONE;

const TIME_ZONE_SETTINGS: Record<RunTimeZone, {label: string; offset: string}> = {
  [RUN_TIME_ZONE]: {label: 'Vietnam time (UTC+07:00)', offset: '+07:00'},
  [INDIA_TIME_ZONE]: {label: 'India time (UTC+05:30)', offset: '+05:30'},
};

export function isRunTimeZone(value: unknown): value is RunTimeZone {
  return value === RUN_TIME_ZONE || value === INDIA_TIME_ZONE;
}

export function runTimeZone(value: unknown): RunTimeZone {
  return isRunTimeZone(value) ? value : RUN_TIME_ZONE;
}

export function readRunTimeZone() {
  return runTimeZone(persistentState.getItem(RUN_TIME_ZONE_STORAGE_KEY));
}

export function runTimeZoneLabel(value: unknown) {
  return TIME_ZONE_SETTINGS[runTimeZone(value)].label;
}

export function scheduleDateTime(value: Date, timeZone: RunTimeZone) {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone,
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'})
    .formatToParts(value);
  const part = (type: string) => parts.find(item => item.type === type)?.value || '';
  return {date: `${part('year')}-${part('month')}-${part('day')}`, time: `${part('hour')}:${part('minute')}`};
}

export function scheduleDateTimeIso(date: string, time: string, timeZone: RunTimeZone) {
  if (!date || !time) return '';
  return `${date}T${time}:00${TIME_ZONE_SETTINGS[timeZone].offset}`;
}

export function formatScheduledTime(value: string | null, timeZone: RunTimeZone = RUN_TIME_ZONE) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en-GB', {timeZone, day: '2-digit', month: 'short',
    year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).format(new Date(value));
}

export function scheduledDayOfMonth(value: string, timeZone: RunTimeZone) {
  return Number(new Intl.DateTimeFormat('en-US', {timeZone, day: 'numeric'}).format(new Date(value)));
}
