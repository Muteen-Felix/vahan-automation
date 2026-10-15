import {estimateBatchTiming, type FilterTiming} from './batch-timing';
import type {RunSchedule} from './run-schedules';

export interface ScheduleTimingObservation {
  key: string;
  done: number;
  receivedAt: number;
  samples: FilterTiming[];
}

function runKey(schedule: RunSchedule) {
  return `${schedule.sessionId}:${schedule.lastRunAt}:${schedule.executionEpoch ?? 0}`;
}

function activeElapsed(schedule: RunSchedule, now: number) {
  if (Number.isFinite(schedule.activeElapsedMs)) {
    const segment = Date.parse(schedule.activeSegmentStartedAt ?? '');
    return Math.max(0, schedule.activeElapsedMs ?? 0) + (Number.isFinite(segment) ? Math.max(0, now - segment) : 0);
  }
  const start = Date.parse(schedule.lastRunAt ?? '');
  return Number.isFinite(start) ? Math.max(0, now - start) : 0;
}

/** Keep output checkpoints for this execution only. The server's real start
 * time supplies the initial average, including after a dashboard reload. */
export function observeScheduleTiming(
  previous: ScheduleTimingObservation | null, schedule: RunSchedule, now: number,
): ScheduleTimingObservation {
  const key = runKey(schedule);
  const startedAt = Date.parse(schedule.lastRunAt ?? '');
  const sameRun = previous?.key === key && schedule.done >= previous.done;
  const samples = sameRun ? previous.samples : [];
  const changed = !sameRun || previous.done !== schedule.done;
  const checkpoint = schedule.status === 'RUNNING' && changed && Number.isFinite(startedAt) && startedAt < now
    ? [{index: schedule.done, durationMs: 0, completedCount: schedule.done, activeElapsedMs: activeElapsed(schedule, now)}]
    : [];
  return {key, done: schedule.done, receivedAt: now, samples: [...samples, ...checkpoint].slice(-256)};
}

export function estimateScheduleTiming(
  schedule: RunSchedule, observation: ScheduleTimingObservation | null, now: number,
) {
  const startedAt = Date.parse(schedule.lastRunAt ?? '');
  const current = observation?.key === runKey(schedule) && observation.done <= schedule.done ? observation : null;
  const stale = Boolean(current && now - current.receivedAt > 15_000);
  const usable = schedule.status === 'RUNNING' && Boolean(schedule.sessionId)
    && Number.isFinite(startedAt) && startedAt < now && schedule.total > 0;
  const estimate = estimateBatchTiming(current?.samples ?? [], schedule.total, schedule.done, null, now,
    usable ? activeElapsed(schedule, now) : 0, null);
  const remainingMs = usable && !stale ? estimate.remainingMs : null;
  return {
    remainingMs,
    finishesAt: remainingMs === null ? null : new Date(now + remainingMs).toISOString(),
    casesPerMinute: remainingMs === null || estimate.reportsPerHour === null ? null : estimate.reportsPerHour / 60,
    stale,
    stalled: usable && !stale && schedule.done > 0 && schedule.done < schedule.total && remainingMs === null,
  };
}

export function formatScheduleDuration(milliseconds: number) {
  // Round up to minutes: a forecast should not imply second-level precision.
  const minutes = Math.max(1, Math.ceil(milliseconds / 60_000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor(minutes % 1440 / 60);
  const rest = minutes % 60;
  return [days ? `${days}d` : '', hours ? `${hours}h` : '', rest ? `${rest}m` : ''].filter(Boolean).join(' ');
}
