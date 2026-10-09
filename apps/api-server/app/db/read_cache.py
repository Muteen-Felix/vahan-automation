"""Bounded, short-lived single-flight cache for non-critical run-list summaries."""
import asyncio,copy,time,weakref
from collections import OrderedDict

_states=weakref.WeakKeyDictionary()
TTL_SECONDS=2
MAX_ENTRIES=128


def state():
    loop=asyncio.get_running_loop()
    if loop not in _states:
        _states[loop]={'entries':OrderedDict(),'pending':{},'generation':{},'hits':0,'loads':0,'coalesced':0}
    return _states[loop]


def invalidate(namespace):
    current=state();current['generation'][namespace]=current['generation'].get(namespace,0)+1
    for key in list(current['entries']):
        if key[0]==namespace:current['entries'].pop(key,None)


def invalidate_report_sessions():
    invalidate('history')


def invalidate_annual_reports():
    invalidate('annual')


def cache_status():
    current=state()
    return {key:current[key] for key in ('hits','loads','coalesced')} | {
        'entries':len(current['entries']),'inFlight':len(current['pending']),'ttlSeconds':TTL_SECONDS}


async def summary_read(key,load):
    current=state();cached=current['entries'].get(key)
    if cached and cached[0]>time.monotonic():
        current['hits']+=1;current['entries'].move_to_end(key)
        return copy.deepcopy(cached[1])
    if cached:current['entries'].pop(key,None)
    namespace=key[0];generation=current['generation'].get(namespace,0);pending_key=(key,generation)
    task=current['pending'].get(pending_key)
    if task is None:
        current['loads']+=1
        async def compute():
            try:
                result=await load()
                if current['generation'].get(namespace,0)==generation:
                    current['entries'][key]=(time.monotonic()+TTL_SECONDS,result)
                    current['entries'].move_to_end(key)
                    while len(current['entries'])>MAX_ENTRIES:current['entries'].popitem(last=False)
                return result
            finally:current['pending'].pop(pending_key,None)
        task=asyncio.create_task(compute());current['pending'][pending_key]=task
    else:current['coalesced']+=1
    # One disconnected HTTP caller must not cancel the read for other callers.
    return copy.deepcopy(await asyncio.shield(task))
