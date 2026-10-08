import {useEffect,useState} from 'react';
import type {RunSchedule} from '../run-schedules';
import {request} from '../services/api-client';

type FailedCase = {position:number;name:string;status:string;attempts:number;failures:number;runnerId:string|null;jobId:string|null;error:string|null};

export function FailedBatchCases({schedule}:{schedule:RunSchedule}) {
  const [open,setOpen]=useState(false),[data,setData]=useState<{session:string;cases:FailedCase[]}>({session:'',cases:[]});
  const [error,setError]=useState(''),[copied,setCopied]=useState(false);
  const session=schedule.sessionId||schedule.lastSessionId;
  const cases=data.session===session?data.cases:[];
  const count=schedule.retryProgress?.failedRemaining??schedule.failed;
  useEffect(()=>{
    if(!open||!session)return;
    let live=true;let timer:ReturnType<typeof setTimeout>;
    const load=async()=>{
      try {
        const snapshot=await request<{tasks:FailedCase[]}>(`/api/batch-queue/sessions/${encodeURIComponent(session)}`);
        if(live){setData({session,cases:snapshot.tasks.filter(task=>(task.status==='FAILED'||task.failures>0)&&!['COMPLETED','NO_DATA'].includes(task.status))});setError('');}
      }catch(reason){if(live)setError(reason instanceof Error?reason.message:'Could not load failed cases.');}
      finally{if(live&&schedule.sessionId)timer=setTimeout(()=>void load(),5000);}
    };
    void load();return()=>{live=false;clearTimeout(timer);};
  },[open,session,schedule.sessionId,count]);
  if(!count||!session)return null;
  return <details className="schedule-failed-cases" onToggle={event=>setOpen(event.currentTarget.open)}>
    <summary>Failed cases ({count})</summary>
    {open&&<>
      <div className="schedule-failed-actions"><span>Original cases and errors stay here until recovery succeeds.</span><button type="button" className="secondary-button" disabled={!cases.length} onClick={async()=>{
        setCopied(false);
        try {await navigator.clipboard.writeText(JSON.stringify({report:schedule.profileName,year:schedule.year,sessionId:session,cases},null,2));setCopied(true);}
        catch {setError('Could not copy failed cases. Allow clipboard access and try again.');}
      }}>{copied?'Copied':'Copy failed cases'}</button></div>
      {error&&<p role="alert" className="schedule-error">{error}</p>}
      <div className="schedule-failed-scroll"><table><thead><tr><th>Case</th><th>Report / error</th><th>Attempts</th><th>Status</th></tr></thead><tbody>
        {cases.length?cases.map(item=><tr key={item.position}><td>{item.position+1}</td><td><strong>{item.name}</strong><p>{item.error||'No error message available.'}</p></td><td>{item.attempts}</td><td>{item.status==='PROCESSING'?'Retrying':item.status==='PENDING'?'Queued for retry':'Still failed'}</td></tr>)
          :<tr><td colSpan={4}>No remaining failed cases.</td></tr>}
      </tbody></table></div>
    </>}
  </details>;
}
