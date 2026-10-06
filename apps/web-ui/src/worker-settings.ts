export const TARGET_WORKER_COUNT = 10;

export function compareRunnerIds(left: string, right: string): number {
  return left.localeCompare(right, undefined, {numeric: true});
}

export function plannedWorkerRange(total: number, workers: number, position: number) {
  const base = Math.floor(total / workers);
  const extra = total % workers;
  const start = position * base + Math.min(position, extra);
  const count = base + (position < extra ? 1 : 0);
  return {start, end: start + count - 1, count};
}
