export interface RunAnalyticsRecord {
  sessionId: string;
  sourceFile: string;
  startedAt: string;
  finishedAt: string;
  durationMs: number;
  filterCount: number;
  applyClicks: number;
  passed: number;
  noData: number;
  failed: number;
  notRun: number;
  status: "completed" | "completed_with_errors" | "stopped" | "error";
  applyCountsByJob: Record<string, number>;
}

interface Props {
  records: RunAnalyticsRecord[];
}

function formatDuration(durationMs: number): string {
  const seconds = Math.max(0, Math.floor(durationMs / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

function formatDelta(value: number): string {
  if (value === 0) return "—";
  return `${value > 0 ? "+" : ""}${value}`;
}

export function RunAnalytics({ records }: Props) {
  return (
    <section className="panel run-analytics" aria-labelledby="runAnalyticsTitle">
      <div className="run-analytics-heading">
        <div>
          <h2 id="runAnalyticsTitle">Run analytics</h2>
          <p>Compare each saved session with the previous run.</p>
        </div>
        <span>{records.length} saved runs</span>
      </div>
      {records.length === 0 ? (
        <p className="run-analytics-empty">No data yet. Session statistics will be saved when a run finishes.</p>
      ) : (
        <div className="run-analytics-table-wrap">
          <table className="run-analytics-table">
            <thead>
              <tr>
                <th>Run</th><th>Filters</th><th>Apply</th><th>Pass</th><th>No data</th><th>Failed</th><th>Not run</th><th>Duration</th><th>Change vs. previous</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record, index) => {
                const previous = records[index + 1];
                const comparison = previous
                  ? `Pass ${formatDelta(record.passed - previous.passed)} · No data ${formatDelta(record.noData - previous.noData)} · Fail ${formatDelta(record.failed - previous.failed)} · Apply ${formatDelta(record.applyClicks - previous.applyClicks)}`
                  : "Latest run";
                const finished = new Date(record.finishedAt);
                const statusLabel = record.status === "completed" ? "Completed"
                  : record.status === "completed_with_errors" ? "Completed with errors"
                    : record.status === "stopped" ? "Stopped" : "Run failed";
                return (
                  <tr key={record.sessionId}>
                    <td>
                      <strong>{finished.toLocaleString("en-GB")}</strong>
                      <span className={`run-analytics-status ${record.status}`}>{statusLabel}</span>
                      <span className="run-analytics-source" title={record.sourceFile}>{record.sourceFile}</span>
                    </td>
                    <td>{record.filterCount}</td>
                    <td>{record.applyClicks}</td>
                    <td className="run-count-pass">{record.passed}</td>
                    <td className="run-count-empty">{record.noData}</td>
                    <td className="run-count-fail">{record.failed}</td>
                    <td>{record.notRun}</td>
                    <td>{formatDuration(record.durationMs)}</td>
                    <td className="run-analytics-comparison">{comparison}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
