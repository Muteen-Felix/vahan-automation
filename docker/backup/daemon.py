"""Hourly encrypted DB snapshots using a read-only role and public age recipient."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from uuid import uuid4

DATA=Path('/data')
TENANT=os.environ['VAHAN_TENANT_ID']
RECIPIENT=os.environ['VAHAN_BACKUP_RECIPIENT']
INTERVAL=int(os.getenv('VAHAN_BACKUP_INTERVAL_SECONDS','3600'))
LIMIT=int(os.getenv('VAHAN_BACKUP_MAX_BYTES',str(20*1024**3)))


def notify(name,payload):
    event={'id':str(uuid4()),'timestamp':datetime.now(timezone.utc).isoformat(),'tenantId':TENANT,
           'service':'backup','actor':None,'event':name,'payload':payload,'context':{}}
    print(json.dumps(event),flush=True)


def snapshot():
    holder=subprocess.Popen(['psql','-X','-qAt','-v','ON_ERROR_STOP=1'],stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    dump=None;encryption=None
    destination=DATA/('backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.dump.age')
    partial=destination.with_suffix('.partial')
    try:
        holder.stdin.write("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
            "SELECT json_build_object('snapshot',pg_export_snapshot(),'counts',json_build_object("
            "'jobs',(SELECT count(*) FROM jobs),'main_reports',(SELECT count(*) FROM main_reports),"
            "'users',(SELECT count(*) FROM users),'stored_files',(SELECT count(*) FROM stored_files)));\n")
        holder.stdin.flush();metadata=json.loads(holder.stdout.readline())
        dump=subprocess.Popen(['pg_dump','-Fc','--snapshot',metadata['snapshot']],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        encryption=subprocess.Popen(['age','-r',RECIPIENT,'-o',str(partial)],stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        digest=hashlib.sha256()
        while chunk:=dump.stdout.read(1024*1024):
            digest.update(chunk);encryption.stdin.write(chunk)
        encryption.stdin.close()
        if dump.wait() or encryption.wait():raise RuntimeError('Snapshot encryption failed')
        partial.replace(destination);os.chmod(destination,0o600)
        manifest={'tenantId':TENANT,'createdAt':datetime.now(timezone.utc).isoformat(),
                  'counts':metadata['counts'],'dumpSha256':digest.hexdigest(),'bytes':destination.stat().st_size}
        with destination.open('rb') as reader:
            encrypted=hashlib.sha256()
            while chunk:=reader.read(1024*1024):encrypted.update(chunk)
        manifest['encryptedSha256']=encrypted.hexdigest()
        path=destination.with_suffix('.json');path.write_text(json.dumps(manifest));os.chmod(path,0o600)
        (DATA/'latest.json').write_text(json.dumps(manifest));os.chmod(DATA/'latest.json',0o600)
        notify('backup.completed',manifest)
        # Only files generated in this managed volume are eligible for pruning.
        files=sorted(DATA.glob('backup-*.dump.age'),key=lambda p:p.stat().st_mtime)
        total=sum(p.stat().st_size for p in files)
        for old in files[:-2]:
            if total<=LIMIT:break
            total-=old.stat().st_size;old.with_suffix('.json').unlink(missing_ok=True);old.unlink()
    finally:
        if dump and dump.poll() is None:dump.kill();dump.wait()
        if encryption and encryption.poll() is None:encryption.kill();encryption.wait()
        if holder.poll() is None:
            holder.stdin.write('ROLLBACK;\n\\q\n');holder.stdin.flush()
        holder.stdin.close();holder.wait(timeout=15);partial.unlink(missing_ok=True)


if __name__=='__main__':
    if not RECIPIENT or INTERVAL<300:raise SystemExit('Configure backup recipient and safe interval.')
    DATA.mkdir(exist_ok=True,mode=0o700);os.chmod(DATA,0o700);os.umask(0o077)
    while True:
        started=time.monotonic()
        try:
            if shutil.disk_usage(DATA).free<512*1024**2:raise RuntimeError('Insufficient backup space')
            snapshot()
        except Exception:notify('backup.failed',{'reason':'snapshot_or_storage_unavailable'})
        time.sleep(max(30,INTERVAL-(time.monotonic()-started)))
