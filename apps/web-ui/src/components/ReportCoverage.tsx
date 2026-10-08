import {useEffect, useMemo} from 'react';
import type {MatrixPlan} from '../matrix-plan';
import {useLiveQuery} from '../hooks/use-live-query';
import {loadReportCoverage, type CoverageContext, type ReportCoverageData} from '../report-coverage';

export function ReportCoverage({context, plan, refreshTrigger}: {
  context: CoverageContext; plan: MatrixPlan; refreshTrigger?: number;
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
  const percent = shown?.total ? 100 * shown.covered / shown.total : 0;
  const complete = Boolean(shown?.matrixLoaded && shown.total > 0 && shown.missing === 0);
  const status = shown?.matrixLoaded ? complete ? 'Complete' : 'In progress' : 'Loading';
  return <section className="report-coverage" aria-label="Main table data coverage">
    <div className="report-coverage-heading">
      <div><h3>Data coverage · {context.year}</h3>
        <span className="coverage-status" data-complete={complete}>{status}</span></div>
      <div className="report-coverage-count"><strong>{shown?.matrixLoaded ? shown.covered.toLocaleString('en-GB') : '—'}</strong>
        <span>/ {shown?.matrixLoaded ? shown.total.toLocaleString('en-GB') : '—'}</span>
        {shown?.matrixLoaded && shown.missing > 0 && <small>{shown.missing.toLocaleString('en-GB')} remaining</small>}</div>
    </div>
    <div className="coverage-progress-track" role="progressbar" aria-label="Main table data coverage"
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Number(percent.toFixed(1))}
      aria-valuetext={shown ? `${shown.covered} of ${shown.total} reports covered` : 'Loading coverage'}>
      <span style={{width: `${percent}%`}} /></div>
    {shown?.matrixLoaded && <div className="report-coverage-details">
      <p><span>Results</span><strong>{shown.withData} with data · {shown.noData} no data</strong></p>
      {shown.firstMissing && <p><span>Next</span><strong>#{shown.firstMissing.index + 1} · {shown.firstMissing.state} · {shown.firstMissing.rto}</strong></p>}
    </div>}
    <details className="report-coverage-more"><summary>Details</summary>
      {shown?.matrixLoaded && <p>Last saved <strong>{shown.lastSaved ? `#${shown.lastSaved.index + 1} · ${shown.lastSaved.state} · ${shown.lastSaved.rto}` : 'No reports yet'}</strong></p>}
    </details>
    {shown?.blockedReason && <p className="report-coverage-note">{shown.blockedReason}</p>}
    {error && <p className="annual-error" role="alert">{error}</p>}
  </section>;
}
