import type {BatchRetryProgress} from '../services/api-client';

export function BatchRetryStatus({progress,running}:{progress:BatchRetryProgress|null|undefined;running:boolean}) {
  if(!progress || progress.phase==='PRIMARY' || progress.phase==='DONE' && !progress.failedRemaining)return null;
  return <div className="batch-retry-status" role="status" data-phase={progress.phase}>
    <strong>{progress.phase==='FINAL'?'Final failed-case recovery':progress.phase==='CHECKPOINT'?'10-case error checkpoint':'Recovery finished'}</strong>
    <p>{progress.phase==='CHECKPOINT'
      ?`Cases ${progress.checkpointStart+1}–${progress.checkpointEnd}: ${progress.pendingRetries} failed cases queued or retrying. The next group waits.`
      :progress.phase==='FINAL'
        ?`${progress.failedRemaining} failed cases remain. Workers are rechecking the full failed list.`
        :`${progress.failedRemaining} cases still failed. Open Failed cases below to review and copy their errors.`}</p>
    {!running&&!progress.complete&&<small>Recovery is paused. Continue the saved run to keep processing these cases.</small>}
  </div>;
}
