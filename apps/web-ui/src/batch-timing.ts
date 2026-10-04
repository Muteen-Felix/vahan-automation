export interface FilterTiming {
  index: number;
  durationMs: number;
  completedCount?: number;
  activeElapsedMs?: number;
}

const RECENT_SAMPLE_COUNT = 8;
const MIN_RECENT_WINDOW_MS = 30_000;
const HOUR_MS = 60 * 60 * 1000;

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
  const remainingCount = Math.max(0, totalCount - completedCount);
  const currentElapsedMs = currentStartedAt === null ? 0 : Math.max(0, now - currentStartedAt);
  const activeElapsedMs = Math.max(0, accumulatedActiveMs)
    + (activeSegmentStartedAt === null ? 0 : Math.max(0, now - activeSegmentStartedAt));

  if (remainingCount === 0) {
    return { remainingMs: 0, reportsPerHour: null, pace: null, activeElapsedMs, currentElapsedMs };
  }

  const checkpoints = samples
    .filter((sample) => Number.isInteger(sample.completedCount)
      && Number.isFinite(sample.activeElapsedMs)
      && Number.isFinite(sample.durationMs)
      && sample.durationMs >= 0)
    .sort((left, right) => (left.completedCount! - right.completedCount!));
  const recent = checkpoints.slice(-RECENT_SAMPLE_COUNT);
  const first = recent[0];
  const last = recent.at(-1);
  const recentCompleted = first && last ? last.completedCount! - first.completedCount! : 0;
  const recentElapsedMs = first && last ? last.activeElapsedMs! - first.activeElapsedMs! : 0;

  let msPerReport: number | null = null;
  let pace: "recent" | "session" | null = null;
  if (recent.length >= 5 && recentCompleted > 0 && recentElapsedMs >= MIN_RECENT_WINDOW_MS) {
    msPerReport = recentElapsedMs / recentCompleted;
    pace = "recent";
  } else if (completedCount > 0) {
    // Use the actual active session clock. This includes dispatch and handoff
    // time while excluding pauses, instead of averaging each filter duration.
    const elapsedBeforeCurrent = Math.max(0, activeElapsedMs - currentElapsedMs);
    if (elapsedBeforeCurrent > 0) {
      msPerReport = elapsedBeforeCurrent / completedCount;
      pace = "session";
    }
  }

  if (msPerReport === null || !Number.isFinite(msPerReport) || msPerReport <= 0) {
    return { remainingMs: null, reportsPerHour: null, pace: null, activeElapsedMs, currentElapsedMs };
  }

  const currentRemainingMs = currentStartedAt === null
    ? 0
    : Math.max(0, msPerReport - currentElapsedMs);
  const futureReports = Math.max(0, remainingCount - (currentStartedAt === null ? 0 : 1));
  const remainingMs = currentRemainingMs + futureReports * msPerReport;

  return {
    remainingMs,
    reportsPerHour: HOUR_MS / msPerReport,
    pace,
    activeElapsedMs,
    currentElapsedMs,
  };
}
