import type {BatchRetryProgress} from '../services/api-client';

export function BatchRetryStatus({progress,running}:{progress:BatchRetryProgress|null|undefined;running:boolean}) {
  if(!progress || progress.phase==='PRIMARY' || progress.phase==='DONE' && !progress.failedRemaining)return null;
  const checkpointSize = Math.max(1, progress.checkpointEnd - progress.checkpointStart);
  return <div className="batch-retry-status" role="status" data-phase={progress.phase}>
    <strong>{progress.phase==='FINAL'?'Final check of unfinished reports':progress.phase==='CHECKPOINT'?`Checking unfinished reports in this group (${checkpointSize})`:'Retry check finished'}</strong>
    <p>{progress.phase==='CHECKPOINT'
      ?`Reports ${progress.checkpointStart+1}–${progress.checkpointEnd}: ${progress.pendingRetries} unfinished reports waiting or being tried again. The next group waits.`
      :progress.phase==='FINAL'
        ?`${progress.failedRemaining} reports still need attention. The system is trying all unfinished reports again.`
        :`${progress.failedRemaining} reports could not finish. Open Reports needing attention below to review them and copy the issues for support.`}</p>
    {!running&&!progress.complete&&<small>Retries are paused. Continue this run to try these reports again.</small>}
  </div>;
}
