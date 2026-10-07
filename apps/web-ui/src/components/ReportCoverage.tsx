import { useEffect, useMemo, useState } from 'react';
import { isReportYear } from '../matrix-plan';
import { useLiveQuery } from '../hooks/use-live-query';
import { loadReportCoverage, type CoverageContext, type CoverageControls, type ReportCoverageData } from '../report-coverage';

const statusLabels: Record<string, string> = {idle: 'Ready', running: 'Running', completed: 'Completed',
  completed_with_errors: 'Completed with errors', stopped: 'Stopped', error: 'Paused'};

export function ReportCoverage({context, controls, refreshTrigger}: {
  context: CoverageContext; controls: CoverageControls; refreshTrigger?: number;
}) {
  const [actionError, setActionError] = useState('');
  const [starting, setStarting] = useState(false);
  const viewKey = JSON.stringify(context);
  const queryKey = useMemo(() => [viewKey, controls.plan], [viewKey, controls.plan]);
  const {data: shown, error: readError, refresh} = useLiveQuery<ReportCoverageData>(queryKey,
    signal => loadReportCoverage(context, controls.plan, signal), 3_000);
  const error = actionError || readError;
  useEffect(() => {
    const refreshVisible = () => {if (!document.hidden) refresh();};
    const timer = window.setInterval(refreshVisible, 5_000);
    window.addEventListener('focus', refreshVisible);
    return () => {window.clearInterval(timer); window.removeEventListener('focus', refreshVisible);};
  }, [refresh]);
  useEffect(() => {refresh();}, [refreshTrigger, refresh]);
  const percent = shown?.total ? 100 * shown.covered / shown.total : 0;
  const complete = Boolean(shown?.matrixLoaded && shown.total > 0 && shown.missing === 0);
  const blocked = controls.busy || starting || controls.loadingMatrix || !isReportYear(context.year)
    || Boolean(shown?.matrixLoaded && !shown.canContinue) || !shown || Boolean(error);
  async function continueMissing() {
    setStarting(true); setActionError('');
    try {await controls.onContinue(context);}
    catch (reason) {setActionError(reason instanceof Error ? reason.message : 'Could not continue the reports.');}
    finally {setStarting(false); refresh(true);}
  }
  return <section className="report-coverage" aria-label="Main table data coverage">
    <div className="report-coverage-heading">
      <div><p className="report-coverage-eyebrow">MAIN TABLE · {context.year}</p><h3>Data coverage</h3>
        <span className="scenario-status-badge" data-status={controls.running ? 'running' : complete ? 'completed' : controls.status}>
          {controls.running ? 'Running' : complete ? 'Fully covered' : statusLabels[controls.status] || 'Ready'}</span></div>
      <div className="report-coverage-count"><strong>{shown?.matrixLoaded ? shown.covered.toLocaleString('en-GB') : '—'}</strong>
        <span>/ {shown?.matrixLoaded ? shown.total.toLocaleString('en-GB') : '—'} reports covered</span>
        <small>{shown?.matrixLoaded ? `${percent.toFixed(1)}% · ${shown.missing.toLocaleString('en-GB')} remaining` : 'Load the State–RTO office list to calculate coverage'}</small></div>
    </div>
    <div className="scenario-progress-track" role="progressbar" aria-label="Main table data coverage"
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Number(percent.toFixed(1))}
      aria-valuetext={shown ? `${shown.covered} of ${shown.total} reports covered` : 'Loading coverage'}>
      <span style={{width: `${percent}%`}} /></div>
    {shown?.matrixLoaded && <div className="report-coverage-details">
      <p><span>Saved results</span><strong>{shown.withData} with data · {shown.noData} confirmed no data</strong></p>
      <p><span>Next missing report</span><strong>{shown.firstMissing ? `#${shown.firstMissing.index + 1} · ${shown.firstMissing.state} · ${shown.firstMissing.rto}` : 'All selected offices are covered'}</strong></p>
    </div>}
    <div className="report-coverage-actions">
      <button type="button" className="primary-button" disabled={blocked || complete || shown?.total === 0 && shown.matrixLoaded}
          onClick={() => void continueMissing()}>{controls.loadingMatrix ? 'Loading offices…' : starting ? 'Checking missing reports…'
            : complete ? 'All reports covered' : shown?.matrixLoaded ? `Continue ${shown.missing.toLocaleString('en-GB')} missing reports` : 'Load offices and continue'}</button>
      {controls.running && <button type="button" className="secondary-button scenario-stop-button" onClick={controls.onStop}>Stop now</button>}
    </div>
    <details className="report-coverage-more"><summary>Coverage details</summary>
      {shown?.matrixLoaded && <p>Last data saved <strong>{shown.lastSaved ? `#${shown.lastSaved.index + 1} · ${shown.lastSaved.state} · ${shown.lastSaved.rto}` : 'No covered reports yet'}</strong></p>}
      {controls.running && controls.current && <p>Current report <strong>{controls.current}</strong></p>}
      <p>Coverage uses saved office reports and confirmed no-data results. Continue fills every missing office in order, including gaps before the stopping point.</p>
    </details>
    {!controls.running && shown?.blockedReason && <p className="report-coverage-note">{shown.blockedReason}</p>}
    {error && <p className="annual-error" role="alert">{error}</p>}
  </section>;
}
