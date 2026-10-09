import {useEffect,useState} from 'react';
import {request} from '../services/api-client';

interface SecurityState {
  tenantId:string; isolation:string; adminMfaRequired:boolean; cookieSecure:boolean;
  collectorConfigured:boolean; pendingEvents:number; lastDeliveredEventAt:string|null;
  uniqueWorkerCredentials:boolean;
}

export function SecurityStatus() {
  const [status,setStatus]=useState<SecurityState|null>(null);
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;
    const refresh=()=>void request<SecurityState>('/api/security/status').then(value=>{
      if(active){setStatus(value);setError('');}
    }).catch(reason=>{if(active)setError(reason instanceof Error?reason.message:'Security status unavailable.');});
    refresh();const timer=setInterval(refresh,30000);
    return()=>{active=false;clearInterval(timer);};
  },[]);
  return <section className="surface-card" aria-label="Security operations">
    <h3>Security operations</h3>
    {error&&<p role="alert">{error}</p>}
    {status?<dl>
      <dt>Enterprise</dt><dd>{status.tenantId} · dedicated environment</dd>
      <dt>Administrator verification</dt><dd>{status.adminMfaRequired?'Two-step verification required':'Two-step verification optional'}</dd>
      <dt>Worker identity</dt><dd>{status.uniqueWorkerCredentials?'Separate credentials':'Shared credentials'}</dd>
      <dt>Security events</dt><dd>{status.collectorConfigured?`${status.pendingEvents} awaiting delivery`:'Collector unavailable'}</dd>
      <dt>Last delivered event</dt><dd>{status.lastDeliveredEventAt?new Date(status.lastDeliveredEventAt).toLocaleString():'Waiting for first delivery'}</dd>
      <dt>Connection</dt><dd>{status.cookieSecure?'HTTPS session':'Local access — enable HTTPS before remote access'}</dd>
    </dl>:<p>Checking security controls…</p>}
  </section>;
}
