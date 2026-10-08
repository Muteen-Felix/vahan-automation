import {useEffect,useState} from 'react';
import {api} from '../services/api-client';
import {uiSocket} from '../services/socket-client';
import {websiteCheckAlerts,websiteCheckBlocked,websiteCheckReport,websiteTargetLabel} from '../ui-health-alerts';

function checkedTime(value: unknown) {
  const date = new Date(typeof value === 'string' ? value : '');
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('en-GB',{timeZone:'Asia/Ho_Chi_Minh',hour12:false});
}

export function UiHealthContract({refreshToken=0,scrollIntoView=false}:{refreshToken?:number;scrollIntoView?:boolean}) {
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
      <div><h2 id="website-check-alerts-title">UI Health</h2><p>The check before starting a run found an issue that needs attention.</p></div>
      <button type="button" className="secondary-button" disabled={!alerts.length} onClick={()=>void copy('all',websiteCheckReport(status!,alerts))}>{copied==='all'?'Copied':'Copy all errors'}</button>
    </div>
    {error&&<p className="error-message" role="alert">{error}</p>}
    {blocked&&status&&<>
      <div className="website-alert-status" data-blocked={blocked}>
        <strong>Run blocked</strong>
        <span>{alerts.length} {alerts.length===1?'issue requires':'issues require'} attention</span>
      </div>
      <p className="website-alert-notice" role="alert">The run could not start. Copy the error for dev, then retry the run after the issue is fixed.</p>
      <div className="website-alert-scroll">
        <table className="website-alert-table" role="table" aria-label="Website changes blocking a run">
          <thead><tr role="row"><th scope="col" role="columnheader">Detected (UTC+7)</th><th scope="col" role="columnheader">Worker</th><th scope="col" role="columnheader">Website issue</th><th scope="col" role="columnheader">Result</th><th scope="col" role="columnheader">Report to dev</th></tr></thead>
          <tbody>{alerts.map(alert=><tr key={alert.id} role="row">
            <td role="cell" data-label="Detected (UTC+7)">{checkedTime(alert.checkedAt)}</td>
            <td role="cell" data-label="Worker">{alert.workers.length?alert.workers.join(', '):'—'}</td>
            <td role="cell" data-label="Website issue"><strong>{websiteTargetLabel(alert.target)}</strong><p>{alert.title}</p><small>{alert.code}</small></td>
            <td role="cell" data-label="Result"><span className="website-alert-blocked">Run blocked</span></td>
            <td role="cell" data-label="Report to dev"><button type="button" className="secondary-button" onClick={()=>void copy(alert.id,websiteCheckReport(status,[alert]))}>{copied===alert.id?'Copied':'Copy for dev'}</button><details><summary>Technical details</summary><pre>{websiteCheckReport(status,[alert])}</pre></details></td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
  </section>;
}
