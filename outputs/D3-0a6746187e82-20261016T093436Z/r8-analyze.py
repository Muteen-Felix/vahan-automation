import harness as h
import json,statistics
from datetime import datetime
records=[json.loads(l) for l in (h.ROOT/'r8-eta-60s.jsonl').read_text(encoding='utf-8').splitlines()]
obs=[json.loads(l) for l in (h.ROOT/'r8-observations.jsonl').read_text(encoding='utf-8').splitlines()]
terminal=json.loads((h.ROOT/'r8-terminal.json').read_text(encoding='utf-8'));s=terminal['schedule']
start=datetime.fromisoformat(s['lastRunAt']);finish=datetime.fromisoformat(s['lastFinishedAt'])
duration=(finish-start).total_seconds();windows={key:[] for key in ['25-50','50-75','75-100']};nulls={key:0 for key in windows};rows=[]
for r in records:
    sc=r['schedule'];total=sc['total'];p=sc['done']/total if total else 0
    actual=(finish-datetime.fromisoformat(r['at'])).total_seconds()*1000;eta=r['eta']['remainingMs'];key='25-50' if .25<=p<.5 else '50-75' if .5<=p<.75 else '75-100' if .75<=p<1 else None
    error=(eta-actual)/actual if eta is not None and actual>0 else None
    if key:
        if error is None:nulls[key]+=1
        else:windows[key].append(abs(error))
    rows.append({'at':r['at'],'done':sc['done'],'total':total,'etaMs':eta,'actualRemainingMs':actual,'absoluteRelativeError':abs(error) if error is not None else None,'window':key})
stats={k:{'samples':len(v),'nullSamples':nulls[k],'median':statistics.median(v) if v else None,'max':max(v) if v else None} for k,v in windows.items()}
offline=[r for r in obs if not r['network'].get('online',True)]
outages=[]
for i,r in enumerate(obs):
    if not r['network'].get('online',True) and (i==0 or obs[i-1]['network'].get('online',True)):outages.append({'startedAt':r['network'].get('changedAt') or r['at'],'finishedAt':None,'firstObservedAt':r['at']})
    if r['network'].get('online',True) and i>0 and not obs[i-1]['network'].get('online',True):outages[-1]['finishedAt']=r['network'].get('changedAt') or r['at']
for o in outages:
    o['durationSeconds']=(datetime.fromisoformat(o['finishedAt'] or obs[-1]['at'])-datetime.fromisoformat(o['startedAt'])).total_seconds()
intervals=[(datetime.fromisoformat(b['at'])-datetime.fromisoformat(a['at'])).total_seconds() for a,b in zip(records,records[1:])]
running=[r for r in obs if r['schedule']['status']=='RUNNING']
worker_sets={tuple(sorted(w['id'] for w in r['schedule'].get('diagnostics',{}).get('workers',[]) if w.get('selected') and w.get('connected'))) for r in running}
manual_pauses=[];automatic_resume=False
for r in obs:
    sc=r['schedule']
    if not r['network'].get('online',True) or sc.get('networkPaused'):automatic_resume=True
    if sc['status'] in ['PAUSED','PAUSING'] and not sc.get('networkPaused'):manual_pauses.append(r)
    if sc['status']=='RESUMING' and not automatic_resume:manual_pauses.append(r)
    if sc['status']=='RUNNING':automatic_resume=False
identity_stable=len(worker_sets)==1 and all(len(x)==3 for x in worker_sets)
valid=duration>=1800 and s['total']>=100 and s['done']==s['total'] and s['failed']==0 and all(stats[k]['samples'] for k in stats) and max(intervals,default=0)<65 and identity_stable and not manual_pauses
threshold=stats['50-75']['median'] is not None and stats['50-75']['median']<=.25 and stats['75-100']['median'] is not None and stats['75-100']['median']<=.15
result={'sha':h.SHA,'start':start.isoformat(),'finish':finish.isoformat(),'durationSeconds':duration,'totalCases':s['total'],'done':s['done'],'withData':s['withData'],'noData':s['noData'],'failed':s['failed'],'eligible':valid,'thresholdPass':threshold,'windows':stats,'sampleCount':len(records),'nullSamplesTotal':sum(r['eta']['remainingMs'] is None for r in records),'sampleIntervalsMinMaxSeconds':[min(intervals),max(intervals)] if intervals else [],'workerIdentitySets':[list(x) for x in worker_sets],'threeWorkersStable':identity_stable,'manualPauseCount':len(manual_pauses),'operatorInterventions':[],'realVahanOutages':outages,'outagesIncludedInErrors':True,'estimator':'Exact final UI source; see eta-engine-provenance.json','formula':'abs((ETA(t) - (finishedAt-t)) / (finishedAt-t))','samples':rows}
h.save('r8-analysis.json',result)
verdict='PASS' if valid and threshold else 'FAIL'
reason=f'{s["done"]}/{s["total"]} real cases, {duration/60:.2f} minutes; 50-75 median={stats["50-75"]["median"]}, 75-100 median={stats["75-100"]["median"]}; operator interventions0; genuine outages included.'
h.ledger('R8',verdict,reason,['r8-analysis.json','r8-eta-60s.jsonl','r8-observations.jsonl','r8-state-events.jsonl','eta-engine-provenance.json','r8-integrity.json'],start.isoformat())
lines=['# R8 — VAHAN thật',f'\nSHA `{h.SHA}`. Kết quả **{verdict}**. {reason}',f'\nBắt đầu `{start.isoformat()}`; kết thúc `{finish.isoformat()}`. Tổng {len(records)} mẫu, ETA null {result["nullSamplesTotal"]}. Không can thiệp; ba runner cố định: {identity_stable}. Mất mạng VAHAN thực: {len(outages)}, được tính vào sai số.','\n| Tiến độ | Mẫu hợp lệ | ETA null | Trung vị abs(e) | Lớn nhất abs(e) |','| --- | --- | --- | --- | --- |']
for key,value in stats.items():
    median=f'{value["median"]*100:.3f}%' if value['median'] is not None else 'N/A'
    maximum=f'{value["max"]*100:.3f}%' if value['max'] is not None else 'N/A'
    lines.append(f'| {key}% | {value["samples"]} | {value["nullSamples"]} | {median} | {maximum} |')
lines+=['\nNgưỡng: trung vị ≤25% tại 50–75%; ≤15% tại 75–100%. Công thức: `abs((ETA − actual_remaining) / actual_remaining)`. `actual_remaining = finishedAt − t`.','\n| UTC | Done / total | ETA phút | Còn lại thực phút | abs(e) |','| --- | --- | --- | --- | --- |']
for row in rows:
    eta=f'{row["etaMs"]/60000:.3f}' if row['etaMs'] is not None else 'null'
    error=f'{row["absoluteRelativeError"]*100:.3f}%' if row['absoluteRelativeError'] is not None else '—'
    lines.append(f'| {row["at"]} | {row["done"]}/{row["total"]} | {eta} | {row["actualRemainingMs"]/60000:.3f} | {error} |')
(h.ROOT/'R8-ETA.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'verdict':verdict,**{k:v for k,v in result.items() if k!='samples'}}))
