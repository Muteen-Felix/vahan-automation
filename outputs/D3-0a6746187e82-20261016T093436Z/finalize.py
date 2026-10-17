import harness as h
import json,hashlib,re,subprocess,collections
def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()
h.login();start=h.now()
gate=h.cmd(['py','-3',str(h.PRE/'d3-package-gate.py'),'--expected-sha',h.SHA,'--expected-manifest-digest',h.ENV['manifestDigest'],'--expected-images-digest',h.ENV['imageArchiveDigest']],timeout=300)
h.save('identity-gate-final.json',gate);assert gate['returncode']==0
r=subprocess.run(['git','status','--porcelain'],cwd=h.SOURCE,capture_output=True,text=True);assert r.returncode==0 and not r.stdout
h.save('source-clean-final.json',{'at':h.now(),'sha':h.SHA,'pristineSourceClean':True,'artifactRebuiltDuringD3':False})
history=h.api('GET','/api/annual-reports/run-history');assert history['status']==200
small=json.loads((h.ROOT/'small-integrity.json').read_text(encoding='utf-8'))
r8=json.loads((h.ROOT/'r8-integrity.json').read_text(encoding='utf-8'))
res=json.loads((h.ROOT/'resilience-integrity.json').read_text(encoding='utf-8'))
isolated=json.loads((h.ROOT/'isolated-runner-integrity.json').read_text(encoding='utf-8'))
byid={r['sessionId']:r for r in history['body']['runs']}
assert history['body']['total']==len(byid)==len(history['body']['runs'])==4
for proof in [small,r8,res,isolated]:
    row=byid[proof['sessionId']];counts=proof['taskStatusCounts']
    assert row['totalCases']==row['processed']==proof['taskCount']
    assert row['withData']==counts.get('COMPLETED',0) and row['noData']==counts.get('NO_DATA',0) and row['failed']==counts.get('FAILED',0)
    assert row['pending']==row['running']==0
assert byid[res['sessionId']]['filterName']=='D3 resilience real VAHAN Kerala 2019'
h.save('run-history-final.json',history)
h.ledger('R1','PASS','Host health/ready probes200. Packaged API restarted first with durable user state and sessions, then again during real VAHAN workload; same durable queue resumed and terminal integrity confirms no missing/duplicate cases.',['baseline-api.json','api-restart.json','resilience-api-restart.json','resilience-api-recovered.json','resilience-integrity.json'],start)
h.ledger('R17','PASS','Exactly four new real sessions and four named Run History rows; terminal counts agree with PostgreSQL case integrity. Retries did not add rows; deleting resilience schedule preserved filter name/results. Actual final browser UI row count matches API; member request forbidden403.',['run-history-final.json','small-integrity.json','r8-integrity.json','resilience-integrity.json','isolated-runner-integrity.json','browser-history-final.json','ui-history-final.png','auth-final.json'],start)
ledger=json.loads((h.ROOT/'checklist.json').read_text(encoding='utf-8'))
exportrow=next(r for r in ledger['items'] if r['item']=='R5')
h.ledger('R5',exportrow['status'],exportrow['reason']+' Actual browser confirmed both export dialogs and downloaded both XLSX files.',exportrow['evidence']+['browser-final-ui.json','browser-export-verification.json','ui-final-export-all-confirm.png','ui-final-export-filtered-confirm.png','ui-export-all.xlsx','ui-export-filtered.xlsx'],exportrow['startedAt'])
r8row=next(r for r in ledger['items'] if r['item']=='R8')
h.ledger('R8',r8row['status'],r8row['reason'],r8row['evidence']+['R8-ETA.md'],r8row['startedAt'])
import importlib.util
spec=importlib.util.spec_from_file_location('log_audit',h.ROOT/'log-audit.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
logs=audit.audit('final');assert logs['ocrStartHttpCodes'].get('200',0)>0
h.ledger('R14','PASS',f"Scanned {logs['serviceLinesScanned']} API/runner log lines from this D3; OCR start HTTP200 count {logs['ocrStartHttpCodes'].get('200',0)}; known-secret, raw OCR/CAPTCHA, inline-image, bearer/credential-URI matches0. Raw logs were not written to evidence.",['log-audit-final.json','log-audit-during-r8.json'],start)
pre=[]
for line in (h.PRE/'evidence-SHA256SUMS').read_text(encoding='utf-8-sig').splitlines():
    checksum,name=line.split('  ',1);assert digest(h.PRE/name)==checksum,name;pre.append(name)
h.save('pre-D3-seal-preserved.json',{'at':h.now(),'verifiedFiles':len(pre),'mismatches':0,'historicalEvidenceMutated':False})
known=h.SECRETS[:]
private=json.loads((h.STAGE/'.d3-private.json').read_text(encoding='utf-8'));known.extend([private['password'],private['idleToken']])
scanned=0;findings=[]
for p in h.ROOT.rglob('*'):
    if not p.is_file() or '__pycache__' in p.parts:continue
    try:text=p.read_text(encoding='utf-8')
    except (UnicodeDecodeError,OSError):continue
    scanned+=1
    if any(v and v in text for v in known) or re.search(r'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{30,}',text):findings.append(p.name)
h.save('evidence-secret-audit.json',{'at':h.now(),'readableFilesScanned':scanned,'findings':findings,'secretValuesWritten':False});assert not findings,findings
import report
report.write()
d=json.loads((h.ROOT/'checklist.json').read_text(encoding='utf-8'));counts=collections.Counter(r['status'] for r in d['items'])
assert all(r['status']=='PASS' for r in d['items'] if r['item'] not in ['S8','S10']),counts
assert all(r['status']=='NOT_RUN' for r in d['items'] if r['item'] in ['S8','S10'])
with (h.ROOT/'REPORT.md').open('a',encoding='utf-8') as f:
    f.write('\nD3 hoàn tất: **23 PASS; 0 FAIL; 2 NOT_RUN theo scope D-02 (S8/S10)**. Không có blocker mới cần sửa source/artifact. Gate danh tính đầu/cuối PASS; seal 258 file pre-D3 được giữ nguyên. Xem [identity-gate-final.json](identity-gate-final.json), [pre-D3-seal-preserved.json](pre-D3-seal-preserved.json), [evidence-secret-audit.json](evidence-secret-audit.json).\n')
    f.write('\n**Blocker mở: không.** Một cửa sổ kiểm dừng runner riêng bị mất mạng VAHAN tự nhiên chồng lên, nên được giữ là cửa sổ không hợp lệ trong [isolated-runner-BLOCKER.json](isolated-runner-BLOCKER.json), không dùng để suy PASS. Sau khi mạng ổn định, kiểm tiếp trên cùng queue với mạng liên tục online, không restart API; job gốc báo đúng Runner disconnected, hai runner còn lại tự hoàn tất14/14 case trước khi container bị dừng được bật lại. Xem [isolated-clean-PASS.json](isolated-clean-PASS.json) và [isolated-clean-progress.jsonl](isolated-clean-progress.jsonl). Đây là các subcheck trong cùng D3, không chạy lại lượt R8.\n')
    f.write('\nR8:1.228 case thật,51,44 phút;52 mẫu cách nhau59,975–60,036 giây; trung vị abs(e)50–75%=6,05%,75–100%=7,03%. Mất mạng VAHAN31,85 giây được tính vào sai số; không có can thiệp vận hành trong R8. Bảng đầy đủ và giá trị lớn nhất: [R8-ETA.md](R8-ETA.md).\n')
    f.write('\nCác điều chỉnh chỉ ở harness, không sửa ứng dụng hoặc gói: [harness-adjustments.json](harness-adjustments.json). Staging được giữ running để review; tài khoản thử đã bị vô hiệu hóa, mọi hostname override được phục hồi và ba runner healthy.\n')
files=sorted(p for p in h.ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='evidence-SHA256SUMS')
(h.ROOT/'evidence-SHA256SUMS').write_text(''.join(digest(p)+'  '+p.relative_to(h.ROOT).as_posix()+'\n' for p in files),encoding='utf-8')
print(json.dumps({'D3':'COMPLETE','counts':dict(counts),'sealedFiles':len(files),'report':str(h.ROOT/'REPORT.md')}))
