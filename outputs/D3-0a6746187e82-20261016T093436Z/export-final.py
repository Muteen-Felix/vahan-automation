import harness as h
import json,zipfile,io,xml.etree.ElementTree as ET,hashlib
from urllib.parse import urlencode
h.login();started=h.now();out={}
def get(path):
    r=h.api('GET',path);assert r['status']==200,h.clean(r);return r['body']
summary=get('/api/annual-reports?year=2018&limit=500')
assert summary['summary']['rows']>0
dataset=summary['datasetId'];base={'year':2018,'dataset':dataset}
def rows(params):
    data=get('/api/annual-reports?'+urlencode({**params,'limit':500}));items=data['rows'];offset=500
    while len(items)<data['summary']['rows']:
        items+=get('/api/annual-reports?'+urlencode({**params,'limit':500,'offset':offset}))['rows'];offset+=500
    return data,items
ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def workbook(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.testzip() is None
        sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        records=sheet.findall('s:sheetData/s:row',ns);result=[]
        for row in records[3:]:
            cells={}
            for c in row.findall('s:c',ns):
                addr=c.attrib['r'];col=''.join(x for x in addr if x.isalpha())
                v=c.find('s:v',ns);text=c.find('s:is',ns)
                cells[col]=''.join(text.itertext()) if text is not None else v.text if v is not None else None
                assert c.find('s:f',ns) is None,'Unexpected spreadsheet formula'
            result.append([cells.get(chr(65+i)) for i in range(17)])
        return result
def compare(name,params,confirm):
    api,items=rows(params)
    r,raw=h.call('GET','/api/annual-reports/export?'+urlencode({**params,**({'confirmAll':'true'} if confirm else {})}))
    assert r['status']==200,h.clean(r)
    headers={k.lower():v for k,v in r['headers'].items()}
    count=int(headers['x-report-row-count']);data=workbook(raw)
    assert count==len(data)==api['summary']['rows']==len(items)
    for i,(actual,expected) in enumerate(zip(data,items),1):
        wanted=[str(i),expected['state'],expected['rto'],expected['rto_code'],expected['maker'],*[str(x) if x is not None else None for x in expected['months']]]
        # Excel may omit empty inline text cells; preserve numeric zero versus blanks.
        assert [x or None for x in actual]==[x or None for x in wanted],(i,actual,wanted)
    (h.ROOT/(name+'.xlsx')).write_bytes(raw)
    out[name]={'at':h.now(),'query':params,'status':r['status'],'headers':r['headers'],'apiSummary':api['summary'],'apiRows':len(items),'workbookRows':len(data),'sha256':hashlib.sha256(raw).hexdigest(),'allCellsMatchAPI':True}
    h.save('export-verification.json',out)
    return api,items
reject=h.api('GET','/api/annual-reports/export?'+urlencode(base));assert reject['status']==409;out['allNeedsConfirmation']=reject
all_api,items=compare('export-all',base,True)
first=items[0];filtered={**base,'state':first['state'],'rto':(first['rto']+' '+first['rto_code']).strip()}
compare('export-filtered',filtered,False)
history=get('/api/annual-reports/history?'+urlencode(base));h.save('actual-annual-history.json',history)
h.ledger('R5','PASS',f'Export all {len(items)} actual manufacturer rows; State/RTO filtered export; XLSX ZIP/XML valid, every cell and row count matches all API pages and X-Report-Row-Count. Unconfirmed Export all rejected409.',['export-verification.json','export-all.xlsx','export-filtered.xlsx','actual-annual-history.json'],started)
print(json.dumps({'R5':'PASS','allRows':len(items),'filtered':out['export-filtered']['workbookRows']}))
