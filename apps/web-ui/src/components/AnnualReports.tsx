import { useEffect, useState } from 'react';
import { api, request } from '../services/api-client';
import { uiSocket } from '../services/socket-client';
import {UpdateHistory} from './UpdateHistory';
import { ReportCoverage } from './ReportCoverage';
import { useLiveQuery } from '../hooks/use-live-query';
import {currentReportYear, MIN_REPORT_YEAR} from '../matrix-plan';
import type { CoverageControls } from '../report-coverage';

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
type AnnualRow = {id: string; state: string; rto: string; rto_code: string; maker: string; months: (number | null)[]};
type SavedReport = {status: string; states: string[]; rtos: string[]; savedAt: string;
  manufacturerRows: number; newRows: number; newMonthValues: number; updatedMonthValues?: number;
  alreadySavedMonthValues: number; conflicts: number};
type AnnualData = {year: number; datasetId: string; datasets: {id: string; label: string}[];
  years: number[]; states: string[]; rtos: string[]; rows: AnnualRow[]; coverage: number[];
  lastSaved?: SavedReport | null; summary: {rows: number; makers: number; offices: number; updatedAt: string | null}};
const PAGE_SIZE = 100;
const dateTime = (value: string | null) => value ? new Date(value).toLocaleString('en-GB', {
  timeZone: 'Asia/Ho_Chi_Minh', day: '2-digit', month: '2-digit', year: 'numeric',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
}) : '—';

function MonthlyData({refreshTrigger, coverageControls}: {refreshTrigger?: number; coverageControls?: CoverageControls}) {
  const [year, setYear] = useState(currentReportYear);
  const [dataset, setDataset] = useState('');
  const [state, setState] = useState('');
  const [rto, setRto] = useState('');
  const [search, setSearch] = useState({state: '', rto: ''});
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
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
    if (offset > 0 && offset >= data.summary.rows) setOffset(0);
  }, [data, dataset, year, offset]);
  useEffect(() => {refreshData();}, [refreshTrigger, refreshData]);
  const shownData = data;
  const total = shownData?.summary.rows ?? 0;
  const searchPending = state !== search.state || rto !== search.rto;
  const hasSearch = Boolean(search.state.trim() || search.rto.trim());
  const exportExcel = async () => {
    if (!shownData || searchPending || exporting || !total) return;
    if (!hasSearch && !window.confirm(`Export all ${total.toLocaleString()} manufacturer rows for ${year} in the selected report to Excel?`)) return;
    const params = new URLSearchParams({year: String(year), dataset: shownData.datasetId,
      state: search.state.trim(), rto: search.rto.trim(), confirmAll: String(!hasSearch)});
    setExporting(true); setExportError('');
    try { await api.downloadFile(`/api/annual-reports/export?${params}`); }
    catch (reason) {setExportError(reason instanceof Error ? reason.message : 'Could not export Excel.');}
    finally {setExporting(false);}
  };
  return <>
    <div className="annual-toolbar">
      <label className="annual-year">Year<select aria-label="Year" value={year} onChange={event => {
        setYear(Number(event.target.value)); setOffset(0);
      }}>{[...new Set([year, ...(data?.years || []), ...Array.from({length: currentReportYear() - MIN_REPORT_YEAR + 1},
        (_, index) => currentReportYear() - index)])].sort((a, b) => b - a)
        .map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Search State<input type="search" list="annual-states" value={state} placeholder="All states"
        onChange={event => setState(event.target.value)} /></label>
      <datalist id="annual-states">{data?.states.map(value => <option key={value} value={value} />)}</datalist>
      <label>Search RTO / code<input type="search" list="annual-rtos" value={rto} placeholder="Name or RTO code"
        onChange={event => setRto(event.target.value)} /></label>
      <datalist id="annual-rtos">{data?.rtos.map(value => <option key={value} value={value} />)}</datalist>
      {(data?.datasets.length ?? 0) > 1 && <label className="annual-scope">Report filters<select aria-label="Report filters" value={dataset || data?.datasetId}
        onChange={event => {setDataset(event.target.value); setOffset(0);}}>
        {data?.datasets.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>}
      <div className="annual-toolbar-actions">
        {(state || rto) && <button type="button" onClick={() => {setState(''); setRto('');}}>Clear</button>}
        <button type="button" className="annual-export-button" onClick={() => void exportExcel()}
          disabled={searchPending || exporting || !shownData || !total}
          title={hasSearch ? 'Export every matching row across all pages' : 'Confirm and export the entire selected report'}>
          {exporting ? 'Exporting…' : hasSearch ? 'Export search to Excel' : 'Export all to Excel'}
        </button>
        <UpdateHistory/>
        <button type="button" onClick={() => {setExportError(''); setRefresh(value => value + 1); refreshData(true);}}
          aria-label="Refresh monthly data">↻ Refresh</button>
      </div>
    </div>
    {error && <p className="annual-error" role="alert">{error}</p>}
    {shownData?.lastSaved && <div className="annual-save-confirmation" role="status" aria-live="polite">
      <strong>{shownData.lastSaved.status === 'no-data' ? 'No record found · Saved in SQL'
        : shownData.lastSaved.status === 'unchanged' ? 'Already saved in main table'
        : shownData.lastSaved.status === 'review' ? 'Saved in main table · Differences recorded'
        : shownData.lastSaved.status === 'updated' ? 'Updated in main table'
        : 'Saved to main table'}</strong>
      <span>{shownData.lastSaved.states.join(', ')} · {shownData.lastSaved.rtos.join(', ')} · {dateTime(shownData.lastSaved.savedAt)}</span>
      {shownData.lastSaved.status !== 'no-data' && <span>
        {shownData.lastSaved.newRows.toLocaleString()} new rows · {shownData.lastSaved.newMonthValues.toLocaleString()} new month values · {shownData.lastSaved.alreadySavedMonthValues.toLocaleString()} month values already saved
        {(shownData.lastSaved.updatedMonthValues ?? 0) > 0 && ` · ${shownData.lastSaved.updatedMonthValues!.toLocaleString()} month values updated`}
        {shownData.lastSaved.conflicts > 0 && ` · ${shownData.lastSaved.conflicts.toLocaleString()} differences recorded`}
      </span>}
    </div>}
    <div className="annual-workspace">
      <section className="annual-sheet" aria-label="Annual manufacturer registrations">
        <div className="annual-table-meta"><span><strong>{total.toLocaleString()}</strong> manufacturer rows · {year}</span>
          <span>{loading ? 'Updating…' : 'Auto-updated'} <span className="annual-dot" /> <b>—</b> no data for this month · <b>0</b> zero registrations</span></div>
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
          <p className="annual-summary-label">Months with source data</p>
          <div className="annual-month-coverage">{MONTHS.map((month, i) => <span key={month} className={shownData?.coverage.includes(i + 1) ? 'available' : ''}>{month}</span>)}</div>
          <p className="annual-summary-label">Last data added · GMT+7</p><time>{dateTime(shownData?.summary.updatedAt ?? null)}</time>
          <p className="annual-policy">Each completed crawl saves immediately. Newer confirmed values update the table, with previous values retained in history.</p>
        </section>
        {coverageControls && <ReportCoverage context={{year, dataset: shownData?.datasetId || dataset, state: search.state, rto: search.rto}}
          controls={coverageControls} refreshTrigger={(refreshTrigger ?? 0) + refresh} />}
      </aside>
    </div>
  </>;
}

export function AnnualReports({refreshTrigger, coverageControls}: {refreshTrigger?: number; coverageControls?: CoverageControls}) {
  return <div className="annual-reports">
    <div className="annual-title"><div><p>MANUFACTURER REGISTRATIONS</p><h2>Exported Reports</h2></div>
    </div>
    <MonthlyData refreshTrigger={refreshTrigger} coverageControls={coverageControls} />
  </div>;
}
