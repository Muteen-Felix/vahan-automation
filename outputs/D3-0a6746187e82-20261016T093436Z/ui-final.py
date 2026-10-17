import harness as h
import json,subprocess,zipfile,xml.etree.ElementTree as ET
assert (h.ROOT/'r8-terminal.json').exists(),'Run only after R8 to avoid changing its time zone'
private=json.loads((h.STAGE/'.d3-private.json').read_text())
h.SECRETS.append(private['idleToken'])
payload={'base':h.ENV['baseUrl'],'username':h.CONFIG.get('VAHAN_UI_AUTH_USERNAME','admin'),'password':h.CONFIG['VAHAN_UI_AUTH_PASSWORD'],'idleToken':private['idleToken'],'idleExpiresAt':private['idleExpiresAt']}
script='process.env.D3_INPUT='+json.dumps(json.dumps(payload))+';\n'+(h.ROOT/'ui-final.mjs').read_text()
container=h.ENV['project']+'-runner-3'
r=subprocess.run(['docker','exec','-i',container,'node'],input=script,capture_output=True,text=True,encoding='utf-8',timeout=240)
h.save('browser-final-ui.json',{'at':h.now(),'sha':h.SHA,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr});assert r.returncode==0,h.clean(r.stderr)
data=json.loads(r.stdout);assert data['uiSocketConnected'] and not data['errors']
for name in data['screenshots']:
    short=name.removeprefix('ui-final-')
    result=h.cmd(['docker','cp',container+':/tmp/d3-'+short,str(h.ROOT/name)]);assert result['returncode']==0,result
for name in ['ui-export-all.xlsx','ui-export-filtered.xlsx']:
    result=h.cmd(['docker','cp',container+':/tmp/d3-'+name,str(h.ROOT/name)]);assert result['returncode']==0,result
proof=[]
assert len(data['downloadResponses'])==2
for name,response in zip(['ui-export-all.xlsx','ui-export-filtered.xlsx'],data['downloadResponses']):
    with zipfile.ZipFile(h.ROOT/name) as z:
        assert z.testzip() is None
        sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        count=len(sheet.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'))-3
    assert response['status']==200 and count==response['rowCount']
    proof.append({'file':name,'workbookDataRows':count,'response':response})
h.save('browser-export-verification.json',proof)
h.ledger('R7b','PASS','Actual browser account setting switches Vietnam/India; Run History displays both correct zone labels and corresponding timestamps. API Once/Monthly offset conversions verified. Restored Vietnam zone after test.',['schedule-contract.json','browser-final-ui.json','ui-final-history-india.png','ui-final-history-vietnam.png'])
print(json.dumps({'R7b':'PASS','historyUIRows':data['historyUIRows'],'UIExports':len(data['exports']),'expiredSessionRedirect':data.get('expiredSessionRedirectsToLogin')}))
