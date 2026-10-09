// Only confirmed SQL-pressure responses are replayed. Callers use checksum-
// guarded report commits, never Apply clicks or arbitrary POST requests.
const PRESSURE_CODES=new Set(['DATABASE_BUSY','DATABASE_TEMPORARILY_UNAVAILABLE','REPORT_PROCESSING_BUSY']);
export async function saveWithBackpressure(operation,{check=()=>{},sleep=ms=>new Promise(r=>setTimeout(r,ms)),onWait=()=>{},maxAttempts=8}={}){
 for(let attempt=1;attempt<=maxAttempts;attempt++){
  check();
  try{return await operation();}
  catch(error){
   if(error.status!==503||!PRESSURE_CODES.has(error.code)||attempt===maxAttempts)throw error;
   const seconds=Math.min(15,Math.max(1,Number(error.retryAfter)||3)*2**Math.min(attempt-1,3));
   onWait(attempt,seconds);await sleep(seconds*1000);check();
  }
 }
}
