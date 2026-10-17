import harness as h
import re,json,hashlib,collections
def audit(label):
    known=h.SECRETS[:]
    private=h.STAGE/'.d3-private.json'
    if private.exists():
        cfg=json.loads(private.read_text());known.extend(v for k,v in cfg.items() if k in ['password','idleToken'] and isinstance(v,str))
    start=json.loads((h.ROOT/'approval.json').read_text())['approvedAtRecorded']
    # Keep raw service logs in process memory only, including on an unexpected sensitive match.
    r=h.compose('logs','--no-color','--since',start,'api','runner');assert r['returncode']==0
    raw=r['stdout']+'\n'+r['stderr'];lines=raw.splitlines()
    checks={'knownSecrets':[],'rawOCRorCaptchaValue':[],'inlineImageData':[],'authorizationOrCredentialURI':[]}
    for index,line in enumerate(lines):
        item={'lineNumber':index+1,'lineSHA256':hashlib.sha256(line.encode()).hexdigest()}
        if any(v in line for v in known):checks['knownSecrets'].append(item)
        if re.search(r'(?:ocr[ _-]?(?:result|text)|captcha[ _-]?(?:answer|text|solution)|recognized[ _-]?text)\s*[:=]',line,re.I):checks['rawOCRorCaptchaValue'].append(item)
        if 'data:image/' in line:checks['inlineImageData'].append(item)
        if re.search(r'Bearer\s+[A-Za-z0-9_-]+\.|postgres(?:ql)?(?:\+asyncpg)?://[^\s]+:[^\s]+@',line):checks['authorizationOrCredentialURI'].append(item)
    codes=collections.Counter()
    for line in lines:
        if '/api/runner/ocr/start' in line:
            m=re.search(r'HTTP/1\.1"\s+(\d+)',line)
            if m:codes[m.group(1)]+=1
    result={'at':h.now(),'sha':h.SHA,'since':start,'rawLogsSaved':False,'serviceLinesScanned':len(lines),'ocrStartHttpCodes':dict(codes),'genericSuccessfulCaptchaMessages':raw.count('Valid captcha detected, auto-submitting...'),'genericRefreshMessages':raw.count('Captcha length not 6, auto-refreshing...'),'sensitiveMatchCounts':{k:len(v) for k,v in checks.items()},'sensitiveMatchesHashedOnly':checks,'scope':'All API and runner Docker logs for this D3; exact known secrets and raw OCR/captcha/image/bearer/credential patterns. No claim about logs outside this stack or time window.'}
    h.save('log-audit-'+label+'.json',result)
    assert not any(checks.values()),'Sensitive logging pattern detected; inspect hashed evidence without publishing raw logs'
    return result
if __name__=='__main__':
    import sys
    r=audit(sys.argv[1] if len(sys.argv)>1 else 'current');print(json.dumps({k:v for k,v in r.items() if k!='sensitiveMatchesHashedOnly'}))
