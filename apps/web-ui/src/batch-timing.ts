export interface FilterTiming {
  index: number;
  durationMs: number;
}

export function estimateBatchTiming(
  samples: FilterTiming[], total: number, done: number,
  currentStartedAt: number | null, now: number,
) {
  const valid = samples.filter((sample) => Number.isFinite(sample.durationMs) && sample.durationMs >= 0);
  const averageMs = valid.length
    ? valid.reduce((sum, sample) => sum + sample.durationMs, 0) / valid.length : null;
  const remainingCount = Math.max(0, total - done);
  const currentElapsedMs = currentStartedAt !== null ? Math.max(0, now - currentStartedAt) : 0;
  const remainingMs = averageMs === null ? null
    : remainingCount === 0 ? 0
      : currentStartedAt === null ? averageMs * remainingCount
        : averageMs * (remainingCount - 1) + Math.max(0, averageMs - currentElapsedMs);
  return { averageMs, remainingMs, sampleCount: valid.length, currentElapsedMs };
}
