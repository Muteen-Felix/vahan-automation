import {operatorMessage} from '../operator-language';
import { useEffect, useRef, useState } from 'react';
import { api, request } from '../services/api-client';
import { uiSocket } from '../services/socket-client';
import { ReportCoverage } from './ReportCoverage';
import { useLiveQuery } from '../hooks/use-live-query';
import {currentReportYear} from '../matrix-plan';
import type {MatrixPlan} from '../matrix-plan';
import {useDisplayTimeZone} from '../display-time-zone';
import {formatUiDateTime, runTimeZoneLabel} from '../run-schedules';

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
type AnnualRow = {id: string; state: string; rto: string; rto_code: string; maker: string; months: (number | null)[]};
type SavedReport = {savedAt: string};
type ExportConfirmation = {year: number; datasetId: string; datasetLabel: string; state: string; rto: string;
  total: number; hasSearch: boolean};
type AnnualData = {year: number; datasetId: string; datasets: {id: string; label: string}[];
  years: number[]; states: string[]; rtos: string[]; rows: AnnualRow[]; coverage: number[];
  runningJobs: number; updatePaused: boolean; lastSaved?: SavedReport | null;
  summary: {rows: number; makers: number; offices: number; updatedAt: string | null}};
const PAGE_SIZE = 100;
function dataFreshness(data: AnnualData | null) {
  if (!data) return null;
  const updatedAt = [data.summary.updatedAt, data.lastSaved?.savedAt].filter((value): value is string => Boolean(value))
    .reduce<string | null>((latest, value) => !latest || Date.parse(value) > Date.parse(latest) ? value : latest, null);
  if (data.runningJobs > 0) return {state: 'updating', label: 'Data is being updated', updatedAt};
  if (data.updatePaused) return {state: 'paused', label: 'Data update paused before completion', updatedAt};
  return {state: 'current', label: 'Data is up to date', updatedAt};
}
function MonthlyData({refreshTrigger, coveragePlan}: {refreshTrigger?: number; coveragePlan?: MatrixPlan | null}) {
  const {timeZone} = useDisplayTimeZone();
  const dateTime = (value: string | null) => formatUiDateTime(value, timeZone, {second: '2-digit'});
  const [year, setYear] = useState(currentReportYear);
  const [dataset, setDataset] = useState('');
  const [state, setState] = useState('');
  const [rto, setRto] = useState('');
  const [search, setSearch] = useState({state: '', rto: ''});
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  const [exportConfirmation, setExportConfirmation] = useState<ExportConfirmation | null>(null);
  const exportDialog = useRef<HTMLDialogElement>(null);
  const exportCancelButton = useRef<HTMLButtonElement>(null);
  const exportConfirmButton = useRef<HTMLButtonElement>(null);
  const exportTriggerButton = useRef<HTMLButtonElement>(null);
  const viewKey = JSON.stringify([year, dataset, search.state, search.rto, offset]);
  const {data, loading, error: readError, refresh: refreshData} = useLiveQuery<AnnualData>(viewKey, signal => {
    const params = new URLSearchParams({year: String(year), dataset, state: search.state, rto: search.rto,
      offset: String(offset), limit: String(PAGE_SIZE)});
    return request<AnnualData>(`/api/annual-reports?${params}`, {signal});
  });
  const error = exportError || readError;
  useEffect(() => {
    const saved = () => {setRefresh(value => value + 1); refreshData();};
    uiSocket.on('reports:updated', saved);
    uiSocket.on('connect', saved);
    return () => {uiSocket.off('reports:updated', saved); uiSocket.off('connect', saved);};
  }, [refreshData]);
  useEffect(() => {
    const timer = window.setTimeout(() => {setSearch({state, rto}); setOffset(0);}, 250);
    return () => window.clearTimeout(timer);
  }, [state, rto]);
  useEffect(() => {
    const reload = () => { if (!document.hidden) {setRefresh(value => value + 1); refreshData();} };
    const timer = window.setInterval(reload, 5_000);
    window.addEventListener('focus', reload);
    document.addEventListener('visibilitychange', reload);
    return () => {window.clearInterval(timer); window.removeEventListener('focus', reload);
      document.removeEventListener('visibilitychange', reload);};
  }, [refreshData]);
  useEffect(() => {
    if (!data) return;
    if (dataset && !data.datasets.some(item => item.id === dataset)) {
        setDataset(''); setOffset(0); return;
    }
    if (data.years.length && !data.years.includes(year)) {
      setYear(data.years[0]); setOffset(0);
    }
    if (offset > 0 && offset >= data.summary.rows) setOffset(0);
  }, [data, dataset, year, offset]);
  useEffect(() => {refreshData();}, [refreshTrigger, refreshData]);
  useEffect(() => {
    const dialog = exportDialog.current;
    if (!dialog) return;
    if (exportConfirmation && !dialog.open) {
      dialog.showModal();
      exportCancelButton.current?.focus();
    } else if (!exportConfirmation && dialog.open) {
      dialog.close();
    }
  }, [exportConfirmation]);
  const shownData = data;
  const freshness = dataFreshness(shownData);
  const total = shownData?.summary.rows ?? 0;
  const searchPending = state !== search.state || rto !== search.rto;
  const hasSearch = Boolean(state.trim() || rto.trim() || search.state.trim() || search.rto.trim());
  const exportExcel = () => {
    if (!shownData || searchPending || exporting || !total) return;
    setExportConfirmation({year, datasetId: shownData.datasetId,
      datasetLabel: shownData.datasets.find(item => item.id === shownData.datasetId)?.label ?? shownData.datasetId,
      state: search.state.trim(), rto: search.rto.trim(), total, hasSearch});
  };
  const confirmExport = async () => {
    if (!exportConfirmation || exporting) return;
    const confirmation = exportConfirmation;
    const params = new URLSearchParams({year: String(confirmation.year), dataset: confirmation.datasetId,
      state: confirmation.state, rto: confirmation.rto});
    if (!confirmation.hasSearch) params.set('confirmAll', 'true');
    exportDialog.current?.close();
    setExportConfirmation(null);
    setExporting(true); setExportError('');
    try { await api.downloadFile(`/api/annual-reports/export?${params}`); }
    catch (reason) {setExportError(reason instanceof Error ? reason.message : 'Could not export Excel.');}
    finally {setExporting(false);}
  };
  return <>
    <div className="annual-toolbar">
      <label className="annual-year">Year<select aria-label="Year"
        value={data?.years.includes(year) ? year : data?.years[0] ?? ''}
        disabled={!data?.years.length}
        onChange={event => {
        setYear(Number(event.target.value)); setOffset(0);
      }}>{data?.years.length ? data.years.map(value => <option key={value} value={value}>{value}</option>)
        : <option value="">{data ? 'No years with data' : 'Loading years…'}</option>}</select></label>
      <label>Search State<input type="search" list="annual-states" value={state} placeholder="All states"
        onChange={event => setState(event.target.value)} /></label>
      <datalist id="annual-states">{data?.states.map(value => <option key={value} value={value} />)}</datalist>
      <label>Search RTO / code<input type="search" list="annual-rtos" value={rto} placeholder="Name or RTO code"
        onChange={event => setRto(event.target.value)} /></label>
      <datalist id="annual-rtos">{data?.rtos.map(value => <option key={value} value={value} />)}</datalist>
      {freshness && <p className="annual-data-status" data-status={freshness.state} role="status"
        aria-label={`${freshness.label}${freshness.updatedAt ? ` · Last updated ${dateTime(freshness.updatedAt)}` : ''}`}
        title={freshness.updatedAt ? `Last updated ${dateTime(freshness.updatedAt)}` : 'No saved data date is available'}>
        <span className="annual-data-status-dot" aria-hidden="true" />{freshness.label}</p>}
      {(data?.datasets.length ?? 0) > 1 && <label className="annual-scope">Report filters<select aria-label="Report filters" value={dataset || data?.datasetId}
        onChange={event => {setDataset(event.target.value); setOffset(0);}}>
        {data?.datasets.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>}
      <div className="annual-toolbar-actions">
        {(state || rto) && <button type="button" onClick={() => {setState(''); setRto('');}}>Clear</button>}
        <button ref={exportTriggerButton} type="button" className="annual-export-button" onClick={exportExcel}
          disabled={searchPending || exporting || !shownData || !total}
          title={hasSearch ? 'Export all rows matching the State and RTO filters' : 'Confirm and export the entire selected report'}>
          {exporting ? 'Exporting…' : hasSearch ? 'Export filtered to Excel' : 'Export all to Excel'}
        </button>
        <button type="button" onClick={() => {setExportError(''); setRefresh(value => value + 1); refreshData(true);}}
          aria-label="Refresh monthly data">↻ Refresh</button>
      </div>
    </div>
    {error && <p className="annual-error" role="alert">{operatorMessage(error)}</p>}
    <div className="annual-workspace">
      <section className="annual-sheet" aria-label="Annual manufacturer registrations">
        <div className="annual-table-meta"><span><strong>{total.toLocaleString()}</strong> manufacturer rows · {year}</span></div>
        <div className="annual-table-scroll" tabIndex={0} role="region" aria-label="Manufacturer data, all 12 months" aria-busy={loading}>
          <table className="annual-table">
            <colgroup><col className="annual-col-number" /><col className="annual-col-state" /><col className="annual-col-rto" />
              <col className="annual-col-code" /><col className="annual-col-maker" />{MONTHS.map(month => <col className="annual-col-month" key={month} />)}</colgroup>
            <thead><tr>{['S.No', 'STATE', 'RTO', 'RTOCode', 'Maker'].map((name, i) => <th key={name} scope="col" className={`annual-identity annual-fixed-${i}`}>{name}</th>)}
              {MONTHS.map(month => <th key={month} scope="col" className="annual-month">{month}’{String(year).slice(-2)}</th>)}</tr></thead>
            <tbody>{shownData?.rows.map((row, index) => <tr key={row.id}>
              <td className="annual-fixed-0">{offset + index + 1}</td><td className="annual-fixed-1">{row.state}</td>
              <td className="annual-fixed-2">{row.rto}</td><td className="annual-fixed-3">{row.rto_code || '—'}</td>
              <th scope="row" className="annual-fixed-4" title={row.maker}>{row.maker}</th>
              {MONTHS.map((month, i) => <td key={month} className={row.months[i] == null ? 'annual-missing' : 'annual-value'}>
                {row.months[i] == null ? '—' : row.months[i]!.toLocaleString('en-US')}</td>)}
            </tr>)}</tbody>
          </table>
          {!shownData?.rows.length && <div className="annual-empty"><strong>{loading ? 'Loading manufacturer data…' : 'No manufacturer rows found'}</strong>
            <p>{state || rto ? 'Try another State or RTO.' : 'Downloaded reports will appear here automatically with their original manufacturer names.'}</p></div>}
        </div>
        <div className="annual-pagination"><span>{total ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total.toLocaleString()}` : '0 rows'}</span>
          <div><button disabled={offset === 0 || !shownData || searchPending} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>← Previous</button>
            <span>Page {Math.floor(offset / PAGE_SIZE) + 1} / {Math.max(1, Math.ceil(total / PAGE_SIZE))}</span>
            <button disabled={offset + PAGE_SIZE >= total || !shownData || searchPending} onClick={() => setOffset(value => value + PAGE_SIZE)}>Next →</button></div></div>
      </section>
      <aside className="annual-insights">
        <section className="annual-summary"><h3>{year} overview</h3>
          <div className="annual-summary-grid"><div><strong>{shownData?.summary.makers.toLocaleString() ?? '—'}</strong><span>Manufacturers</span></div>
            <div><strong>{shownData?.summary.offices.toLocaleString() ?? '—'}</strong><span>RTO offices</span></div></div>
          <p className="annual-summary-label">Months with data</p>
          <div className="annual-month-coverage">{MONTHS.map((month, i) => <span key={month} className={shownData?.coverage.includes(i + 1) ? 'available' : ''}>{month}</span>)}</div>
          <p className="annual-summary-label">Last updated · {runTimeZoneLabel(timeZone)}</p><time>{dateTime(shownData?.summary.updatedAt ?? null)}</time>
        </section>
        <ReportCoverage context={{year, dataset: shownData?.datasetId || dataset, state: search.state, rto: search.rto}}
          plan={coveragePlan ?? null} refreshTrigger={(refreshTrigger ?? 0) + refresh} />
      </aside>
    </div>
    <dialog ref={exportDialog} className="annual-export-dialog" aria-labelledby="annual-export-title"
      aria-describedby="annual-export-description"
      onCancel={event => {event.preventDefault(); setExportConfirmation(null);}}
      onClose={() => {exportTriggerButton.current?.focus();}}
      onClick={event => {if (event.target === event.currentTarget) setExportConfirmation(null);}}
      onKeyDown={event => {
        if (event.key !== 'Tab') return;
        if (event.shiftKey && document.activeElement === exportCancelButton.current) {
          event.preventDefault(); exportConfirmButton.current?.focus();
        } else if (!event.shiftKey && document.activeElement === exportConfirmButton.current) {
          event.preventDefault(); exportCancelButton.current?.focus();
        }
      }}>
      {exportConfirmation && <div className="annual-export-dialog-content">
        <p className="annual-export-dialog-eyebrow">EXCEL EXPORT</p>
        <h2 id="annual-export-title">{exportConfirmation.hasSearch ? 'Export filtered results?' : 'Export the full report?'}</h2>
        <p id="annual-export-description" className="annual-export-dialog-summary">
          Export <strong>{exportConfirmation.total.toLocaleString()}</strong> manufacturer rows for <strong>{exportConfirmation.year}</strong> to Excel?
        </p>
        <p className="annual-export-dialog-scope">
          {exportConfirmation.hasSearch
            ? `Filters: ${[exportConfirmation.state && `State: ${exportConfirmation.state}`,
              exportConfirmation.rto && `RTO: ${exportConfirmation.rto}`].filter(Boolean).join(' · ')}`
            : `Report: ${exportConfirmation.datasetLabel}`}
        </p>
        <p className="annual-export-dialog-note">Rows from every page will be included in the Excel file.</p>
        <div className="annual-export-dialog-actions">
          <button ref={exportCancelButton} type="button" onClick={() => setExportConfirmation(null)}>Cancel</button>
          <button ref={exportConfirmButton} type="button" className="annual-export-dialog-confirm" onClick={() => void confirmExport()}>
            Export to Excel
          </button>
        </div>
      </div>}
    </dialog>
  </>;
}

export function AnnualReports({refreshTrigger, coveragePlan}: {refreshTrigger?: number; coveragePlan?: MatrixPlan | null}) {
  return <div className="annual-reports">
    <div className="annual-title"><div><p>MANUFACTURER REGISTRATIONS</p><h2>Exported Reports</h2></div>
    </div>
    <MonthlyData refreshTrigger={refreshTrigger} coveragePlan={coveragePlan} />
  </div>;
}
