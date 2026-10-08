export interface RunSchedule {
  id: string;
  profileId: string;
  profileName: string;
  profileRevision: number;
  year: number;
  workerCount: number;
  startsAt: string;
  nextRunAt: string | null;
  repeat: 'once' | 'daily';
  timeZone: string;
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
  repeat: 'once' | 'daily';
}

export interface CurrentCaptcha {
  jobId: string;
  runnerId: string;
  captchaId: string;
  scenarioName: string | null;
}

export const RUN_TIME_ZONE = 'Asia/Ho_Chi_Minh';

export function vietnamDateTime(value: Date) {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone: RUN_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'})
    .formatToParts(value);
  const part = (type: string) => parts.find(item => item.type === type)?.value || '';
  return {date: `${part('year')}-${part('month')}-${part('day')}`, time: `${part('hour')}:${part('minute')}`};
}

export function formatScheduledTime(value: string | null) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en-GB', {timeZone: RUN_TIME_ZONE, day: '2-digit', month: 'short',
    year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).format(new Date(value));
}
