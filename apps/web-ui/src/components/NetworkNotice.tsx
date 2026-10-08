import {useEffect, useState} from 'react';
import {request} from '../services/api-client';
import {uiSocket} from '../services/socket-client';

type ServerNetwork = {online: boolean; checkedAt?: string; message?: string};
export function useNetworkStatus() {
  const [browserOnline,setBrowserOnline] = useState(navigator.onLine);
  const [reachable,setReachable] = useState(true);
  const [server,setServer] = useState<ServerNetwork | null>(null);
  useEffect(()=>{
    let live=true;let timer:ReturnType<typeof setTimeout>;let controller:AbortController | null=null;let sequence=0;
    const refresh=async()=>{
      const version=++sequence;
      controller?.abort();const current=new AbortController();controller=current;
      const deadline=setTimeout(()=>current.abort(),4000);
      if(!navigator.onLine){setBrowserOnline(false);clearTimeout(deadline);return;}
      try {
        const state=await request<ServerNetwork>('/api/network/status',{signal:current.signal});
        if(!state || typeof state.online!=='boolean')return; // Older servers during rollout.
        if(live&&version===sequence){setReachable(true);setServer(state);setBrowserOnline(true);}
      } catch {if(live&&version===sequence)setReachable(false);}
      finally{clearTimeout(deadline);}
    };
    const poll=async()=>{await refresh();if(live)timer=setTimeout(()=>void poll(),3000);};
    const online=()=>{setBrowserOnline(true);void refresh();};
    const offline=()=>{setBrowserOnline(false);setReachable(false);};
    const received=(value:ServerNetwork)=>{if(typeof value?.online==='boolean'){sequence++;controller?.abort();setServer(value);setReachable(true);}};
    window.addEventListener('online',online);window.addEventListener('offline',offline);uiSocket.on('network:status',received);
    void poll();
    return()=>{live=false;sequence++;clearTimeout(timer);controller?.abort();window.removeEventListener('online',online);window.removeEventListener('offline',offline);uiSocket.off('network:status',received);};
  },[]);
  return {browserOnline,reachable,server,offline:!browserOnline||!reachable||server?.online===false};
}
export function NetworkNotice({network}: {network:ReturnType<typeof useNetworkStatus>}) {
  if(!network.offline)return null;
  const upstream=network.browserOnline&&network.reachable&&network.server?.online===false;
  return <div className="network-notice" role="alert"><span aria-hidden="true">⚠</span><div>
    <strong>{upstream?'Network unavailable · reports paused':!network.browserOnline?'Your browser is offline':'Connection to the system was lost'}</strong>
    <p>{upstream?'Interrupted cases are saved in the queue. Work resumes automatically after the connection is stable.':'Trying to reconnect. Saved report progress is preserved; live status will return when the connection is restored.'}</p>
  </div><span className="network-notice-status">Reconnecting…</span></div>;
}
