import {operatorMessage} from '../operator-language';
import {useEffect, useMemo} from 'react';
import type {MatrixPlan} from '../matrix-plan';
import {useLiveQuery} from '../hooks/use-live-query';
import {loadReportCoverage, type CoverageContext, type ReportCoverageData} from '../report-coverage';

function statusLabel(data: ReportCoverageData | null | undefined) {
  if (!data) return 'Loading';
  if (!data.hasRun) return 'No update yet';
  const labels: Record<string, string> = {
    RUNNING: 'In progress', PAUSED: 'Paused', PAUSING: 'Pausing', STOPPED: 'Stopped',
    RESUMING: 'Resuming', PREPARING: 'Preparing', COMPLETED: 'Complete',
    COMPLETED_WITH_ERRORS: 'Completed with errors', ERROR: 'Update error', UNKNOWN: 'Progress unavailable',
  };
  return labels[data.status] ?? data.status;
}

export function ReportCoverage({context, plan, refreshTrigger}: {
  context: CoverageContext; plan: MatrixPlan | null; refreshTrigger?: number;
}) {
  const viewKey = JSON.stringify(context);
  const queryKey = useMemo(() => [viewKey, plan], [viewKey, plan]);
  const {data: shown, error, refresh} = useLiveQuery<ReportCoverageData>(queryKey,
    signal => loadReportCoverage(context, plan, signal), 3_000);
  useEffect(() => {
    const refreshVisible = () => {if (!document.hidden) refresh();};
    const timer = window.setInterval(refreshVisible, 5_000);
    window.addEventListener('focus', refreshVisible);
    return () => {window.clearInterval(timer); window.removeEventListener('focus', refreshVisible);};
  }, [refresh]);
  useEffect(() => {refresh();}, [refreshTrigger, refresh]);

  const hasRun = Boolean(shown?.hasRun && shown.total > 0);
  const processed = Math.min(shown?.processed ?? 0, shown?.total ?? 0);
  const percent = hasRun ? Math.max(0, Math.min(100, processed / shown!.total * 100)) : 0;
  const complete = hasRun && ['COMPLETED', 'COMPLETED_WITH_ERRORS'].includes(shown!.status);
  const remaining = hasRun ? Math.max(0, shown!.total - processed) : 0;
  const label = statusLabel(shown);

  return <section className="report-coverage" aria-label="Latest report update progress" aria-busy={!shown}>
    <div className="report-coverage-heading">
      <div><h3>Reports collected · {context.year}</h3>
        <span className="coverage-status" data-complete={complete} data-status={shown?.status ?? 'LOADING'}>{label}</span></div>
      <div className="report-coverage-count">
        <strong>{hasRun ? `${Math.round(percent)}%` : '—'}</strong>
        <span>{hasRun ? `${processed.toLocaleString('en-GB')} / ${shown!.total.toLocaleString('en-GB')} cases processed`
          : 'No update run for this year'}</span>
        {hasRun && remaining > 0 && <small>{remaining.toLocaleString('en-GB')} remaining</small>}
      </div>
    </div>
    <div className="coverage-progress-track" role="progressbar" aria-label="Latest report update progress"
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Number(percent.toFixed(1))}
      aria-valuetext={hasRun ? `${processed} of ${shown!.total} update cases processed (${percent.toFixed(1)}%)`
        : 'No update has run for this report year'}>
      <span style={{width: `${percent}%`}} /></div>
    {shown && <div className="report-coverage-details">
      {hasRun ? <>
        <p><span>Results</span><strong>{shown.withData.toLocaleString('en-GB')} with data · {shown.noData.toLocaleString('en-GB')} no data
          {shown.failed > 0 && ` · ${shown.failed.toLocaleString('en-GB')} failed`}</strong></p>
      </> : <p><span>Latest update</span><strong>No update run is available for this report yet.</strong></p>}
    </div>}
    {error && <p className="annual-error" role="alert">{operatorMessage(error)}</p>}
  </section>;
}
