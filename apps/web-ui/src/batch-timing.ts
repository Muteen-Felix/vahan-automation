export interface FilterTiming {
  index: number;
  durationMs: number;
  completedCount?: number;
  activeElapsedMs?: number;
}

const HOUR_MS = 60 * 60 * 1000;
const RECENT_WINDOW_MS = 90_000;
const STALLED_AFTER_MS = 120_000;

/** Forecast from observed *system output per wall-clock second*, including
 * worker handoff, database saves and retries. Individual filter times never
 * enter the throughput calculation. */
export function estimateBatchTiming(
  samples: FilterTiming[],
  total: number,
  done: number,
  currentStartedAt: number | null,
  now: number,
  accumulatedActiveMs = 0,
  activeSegmentStartedAt: number | null = null,
) {
  const totalCount = Number.isFinite(total) ? Math.max(0, Math.floor(total)) : 0;
  const completedCount = Number.isFinite(done) ? Math.min(totalCount, Math.max(0, Math.floor(done))) : 0;
  const remainingCount = totalCount - completedCount;
  const currentElapsedMs = currentStartedAt === null ? 0 : Math.max(0, now - currentStartedAt);
  const activeElapsedMs = Math.max(0, accumulatedActiveMs)
    + (activeSegmentStartedAt === null ? 0 : Math.max(0, now - activeSegmentStartedAt));
  if (remainingCount === 0) {
    return {remainingMs: 0, reportsPerHour: null, pace: null, activeElapsedMs, currentElapsedMs};
  }
  if (completedCount === 0 || activeElapsedMs <= 0) {
    return {remainingMs: null, reportsPerHour: null, pace: null, activeElapsedMs, currentElapsedMs};
  }

  const checkpoints = samples.filter((sample) => Number.isInteger(sample.completedCount)
    && Number.isFinite(sample.activeElapsedMs) && sample.activeElapsedMs! >= 0
    && sample.completedCount! > 0 && sample.completedCount! <= completedCount)
    .sort((left, right) => left.activeElapsedMs! - right.activeElapsedMs!);
  const latest = checkpoints.at(-1);
  if (latest && activeElapsedMs - latest.activeElapsedMs! > STALLED_AFTER_MS) {
    return {remainingMs: null, reportsPerHour: null, pace: null, activeElapsedMs, currentElapsedMs};
  }

  const sessionRate = completedCount / activeElapsedMs;
  const windowStart = Math.max(0, activeElapsedMs - RECENT_WINDOW_MS);
  let baseCount = 0;
  let baseTime = 0;
  for (const checkpoint of checkpoints) {
    if (checkpoint.activeElapsedMs! > windowStart) break;
    baseCount = checkpoint.completedCount!;
    baseTime = checkpoint.activeElapsedMs!;
  }
  const recentCompleted = completedCount - baseCount;
  const recentElapsedMs = activeElapsedMs - baseTime;
  const useRecent = completedCount >= 12 && recentCompleted >= 6 && recentElapsedMs >= 15_000;
  const recentRate = useRecent ? recentCompleted / recentElapsedMs : 0;
  // The long window damps completion bursts; the rolling window follows
  // congestion, CAPTCHA waits and changes in healthy worker count.
  const rate = useRecent ? 0.75 * recentRate + 0.25 * sessionRate : sessionRate;
  if (!Number.isFinite(rate) || rate <= 0) {
    return {remainingMs: null, reportsPerHour: null, pace: null, activeElapsedMs, currentElapsedMs};
  }
  return {
    remainingMs: remainingCount / rate,
    reportsPerHour: rate * HOUR_MS,
    pace: useRecent ? 'recent' as const : 'session' as const,
    activeElapsedMs,
    currentElapsedMs,
  };
}
