import {useEffect,useState} from 'react';
import {api} from '../services/api-client';
import {uiSocket} from '../services/socket-client';
import {websiteCheckAlerts,websiteCheckBlocked,websiteCheckReport,websiteTargetLabel} from '../ui-health-alerts';
import {operatorMessage,websiteIssueMessage} from '../operator-language';
import {useDisplayTimeZone} from '../display-time-zone';
import {formatUiDateTime, runTimeZoneLabel, type RunTimeZone} from '../run-schedules';

function checkedTime(value: unknown, timeZone: RunTimeZone) {
  return formatUiDateTime(typeof value === 'string' ? value : '', timeZone, {hour12: false});
}

export function UiHealthContract({refreshToken=0,scrollIntoView=false}:{refreshToken?:number;scrollIntoView?:boolean}) {
  const {timeZone} = useDisplayTimeZone();
  const [status,setStatus] = useState<Record<string,unknown>|null>(null);
  const [error,setError] = useState('');
  const [copied,setCopied] = useState<string|null>(null);
  useEffect(()=>{
    let live=true,sequence=0;
    const load=async()=>{
      const request=++sequence;
      try {
        const next=await api.uiHealthStatus();
        if(live&&request===sequence){setStatus(next);setError('');setCopied(null);}
      } catch(reason) {if(live&&request===sequence)setError(reason instanceof Error?reason.message:'Could not load website check alerts.');}
    };
    void load();uiSocket.on('ui-health:blocked',load);uiSocket.on('ui-health:verified',load);
    return()=>{live=false;uiSocket.off('ui-health:blocked',load);uiSocket.off('ui-health:verified',load);};
  },[refreshToken]);
  const alerts=status?websiteCheckAlerts(status):[];
  const blocked=status?websiteCheckBlocked(status):false;
  useEffect(()=>{
    if(!scrollIntoView||(!blocked&&!error))return;
    const frame=window.requestAnimationFrame(()=>document.getElementById('settings-ui-health')?.scrollIntoView({block:'start'}));
    return()=>window.cancelAnimationFrame(frame);
  },[scrollIntoView,blocked,error]);
  async function copy(id:string,text:string) {
    setCopied(null);
    try {await navigator.clipboard.writeText(text);setCopied(id);setError('');}
    catch {setError('Could not copy the report. Allow clipboard access and try again.');}
  }
  if (!blocked && !error) return null;
  return <section className="panel website-check-alerts settings-ui-health" id="settings-ui-health" aria-labelledby="website-check-alerts-title">
    <div className="website-alert-heading">
      <div><h2 id="website-check-alerts-title">Website check</h2><p>The VAHAN website must be ready before reports can be collected.</p></div>
      <button type="button" className="secondary-button" disabled={!alerts.length} onClick={()=>void copy('all',websiteCheckReport(status!,alerts))}>{copied==='all'?'Copied':'Copy all issues'}</button>
    </div>
    {error&&<p className="error-message" role="alert">{operatorMessage(error)}</p>}
    {blocked&&status&&<>
      <div className="website-alert-status" data-blocked={blocked}>
        <strong>Cannot start yet</strong>
        <span>{alerts.length} {alerts.length===1?'issue requires':'issues require'} attention</span>
      </div>
      <p className="website-alert-notice" role="alert">The run could not start. A listed browser stays blocked until it reconnects and passes a valid UI Health check. Then rerun preflight; every selected browser must pass before work resumes. Copy the issue for support, then check again.</p>
      <div className="website-alert-scroll">
        <table className="website-alert-table" role="table" aria-label="Website changes blocking a run">
          <thead><tr role="row"><th scope="col" role="columnheader">Detected ({runTimeZoneLabel(timeZone)})</th><th scope="col" role="columnheader">Report browsers</th><th scope="col" role="columnheader">Website issue</th><th scope="col" role="columnheader">Result</th><th scope="col" role="columnheader">Share with support</th></tr></thead>
          <tbody>{alerts.map(alert=><tr key={alert.id} role="row">
            <td role="cell" data-label={`Detected (${runTimeZoneLabel(timeZone)})`}>{checkedTime(alert.checkedAt, timeZone)}</td>
            <td role="cell" data-label="Report browsers">{alert.workers.length ? alert.workers.join(', ') : '—'}</td>
            <td role="cell" data-label="Website issue"><strong>{websiteTargetLabel(alert.target)}</strong><p>{websiteIssueMessage(alert.code,alert.title)}</p></td>
            <td role="cell" data-label="Result"><span className="website-alert-blocked">Cannot start yet</span></td>
            <td role="cell" data-label="Share with support"><button type="button" className="secondary-button" onClick={()=>void copy(alert.id,websiteCheckReport(status,[alert]))}>{copied===alert.id?'Copied':'Copy for support'}</button><details><summary>Details for support</summary><pre>{websiteCheckReport(status,[alert])}</pre></details></td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
  </section>;
}
