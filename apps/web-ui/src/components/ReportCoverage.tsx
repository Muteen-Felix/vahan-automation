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
  return <section className="report-coverage" aria-label="Main table data coverage">
    <div className="report-coverage-heading">
      <div><p className="report-coverage-eyebrow">MAIN TABLE · {context.year}</p><h3>Data coverage</h3>
        <span className="coverage-status" data-complete={complete}>{complete ? 'Fully covered' : 'Saved coverage'}</span></div>
      <div className="report-coverage-count"><strong>{shown?.matrixLoaded ? shown.covered.toLocaleString('en-GB') : '—'}</strong>
        <span>/ {shown?.matrixLoaded ? shown.total.toLocaleString('en-GB') : '—'} reports covered</span>
        <small>{shown?.matrixLoaded ? `${percent.toFixed(1)}% · ${shown.missing.toLocaleString('en-GB')} remaining` : 'Waiting for the office list'}</small></div>
    </div>
    <div className="coverage-progress-track" role="progressbar" aria-label="Main table data coverage"
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Number(percent.toFixed(1))}
      aria-valuetext={shown ? `${shown.covered} of ${shown.total} reports covered` : 'Loading coverage'}>
      <span style={{width: `${percent}%`}} /></div>
    {shown?.matrixLoaded && <div className="report-coverage-details">
      <p><span>Saved results</span><strong>{shown.withData} with data · {shown.noData} confirmed no data</strong></p>
      <p><span>Next missing report</span><strong>{shown.firstMissing ? `#${shown.firstMissing.index + 1} · ${shown.firstMissing.state} · ${shown.firstMissing.rto}` : 'All selected offices are covered'}</strong></p>
    </div>}
    <details className="report-coverage-more"><summary>Coverage details</summary>
      {shown?.matrixLoaded && <p>Last data saved <strong>{shown.lastSaved ? `#${shown.lastSaved.index + 1} · ${shown.lastSaved.state} · ${shown.lastSaved.rto}` : 'No covered reports yet'}</strong></p>}
      <p>Coverage uses saved office reports and confirmed no-data results.</p>
    </details>
    {shown?.blockedReason && <p className="report-coverage-note">{shown.blockedReason}</p>}
    {error && <p className="annual-error" role="alert">{error}</p>}
  </section>;
}
