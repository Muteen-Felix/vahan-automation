"""Authenticated age backups; private identities are never included in archives."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time
from environment import read_env
from secure_permissions import restrict_permissions

ROOT = Path(__file__).resolve().parents[1]


def hash_stream(reader):
    digest = hashlib.sha256()
    while data := reader.read(1024 * 1024): digest.update(data)
    return digest.hexdigest()


def identity(path):
    if not shutil.which('age') or not shutil.which('age-keygen'):
        raise RuntimeError('Install age and age-keygen before creating or restoring encrypted backups.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    restrict_permissions(path.parent, directory=True)
    if not path.exists():
        result = subprocess.run(['age-keygen', '-o', str(path)], capture_output=True, text=True)
        if result.returncode: raise RuntimeError('Could not create backup identity.')
    restrict_permissions(path)
    result = subprocess.run(['age-keygen', '-y', str(path)], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def compose(env):
    values = read_env(env)
    return ['docker', 'compose', '--project-directory', str(ROOT), '-f', str(ROOT/'compose.yaml'),
            '--env-file', str(env), '-p', values.get('COMPOSE_PROJECT_NAME', 'vahan-automation')]


def metadata(command):
    sql = """BEGIN READ ONLY;
SELECT json_build_object('schemaVersion',(SELECT version_num FROM alembic_version),
 'counts',json_build_object('jobs',(SELECT count(*) FROM jobs),
 'main_reports',(SELECT count(*) FROM main_reports),'users',(SELECT count(*) FROM users),
 'stored_files',(SELECT count(*) FROM stored_files)));
ROLLBACK;"""
    result = subprocess.run([*command,'exec','-T','postgres','psql','-X','-U','vahan','-d','vahan','-At'],
                            input=sql, capture_output=True, text=True, check=True)
    return next(json.loads(line) for line in result.stdout.splitlines() if line.startswith('{'))


SNAPSHOT_CODE = """import asyncio,asyncpg,json,sys
from app.config import settings
async def main():
 connection=await asyncpg.connect(settings.database_url.replace('postgresql+asyncpg://','postgresql://',1))
 try:
  async with connection.transaction(isolation='repeatable_read',readonly=True):
   snapshot=await connection.fetchval('SELECT pg_export_snapshot()')
   schema=await connection.fetchval('SELECT version_num FROM alembic_version')
   counts={name:await connection.fetchval('SELECT count(*) FROM '+name) for name in ['jobs','main_reports','users','stored_files']}
   print(json.dumps({'snapshot':snapshot,'database':{'schemaVersion':schema,'counts':counts}}),flush=True)
   await asyncio.to_thread(sys.stdin.read,1)
 finally:await connection.close()
asyncio.run(main())
"""


def decrypt_verify(backup, key, folder):
    archive = folder / 'verified.tar'
    result = subprocess.run(['age','-d','-i',str(key),'-o',str(archive),str(backup)],
                            capture_output=True, text=True)
    if result.returncode: raise RuntimeError('Backup authentication/decryption failed.')
    restrict_permissions(archive)
    with tarfile.open(archive) as reader:
        members = reader.getmembers()
        if {m.name for m in members} != {'database.dump', '.docker.env', 'manifest.json'} or any(not m.isfile() for m in members):
            raise RuntimeError('Invalid backup archive structure.')
        manifest_member = reader.getmember('manifest.json')
        if manifest_member.size > 1024 * 1024: raise RuntimeError('Invalid backup manifest.')
        manifest = json.load(reader.extractfile(manifest_member))
        for name in ['database.dump','.docker.env']:
            with reader.extractfile(name) as data:
                if hash_stream(data) != manifest['sha256'][name]: raise RuntimeError('Backup checksum mismatch.')
        return manifest


def create(env, destination=None):
    env = Path(env).resolve()
    values = read_env(env)
    tenant = values.get('VAHAN_TENANT_ID','legacy')
    key = Path(values['VAHAN_BACKUP_IDENTITY_FILE']).expanduser()
    key = (key if key.is_absolute() else ROOT/key).resolve()
    recipient = identity(key)
    target = Path(destination or ROOT/'backups'/tenant/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    if key == target or target in key.parents: raise RuntimeError('Backup identity must be outside the archive directory.')
    target.mkdir(parents=True, mode=0o700, exist_ok=False)
    restrict_permissions(target, directory=True)
    os.umask(0o077)
    command = compose(env)
    with tempfile.TemporaryDirectory(prefix='vahan-backup-') as name:
        folder = Path(name)
        dump = folder/'database.dump'
        roles = subprocess.run([*command,'exec','-T','postgres','psql','-X','-U','vahan','-d','vahan','-Atc',
            "SELECT 1 FROM pg_roles WHERE rolname='vahan_backup'"],capture_output=True,text=True,check=True)
        role = 'vahan_backup' if roles.stdout.strip() == '1' else 'vahan'
        # Metadata and dump use the same exported snapshot, so ongoing jobs
        # cannot make a valid backup fail its row-count verification.
        holder = subprocess.Popen([*command,'exec','-T','postgres','psql','-X','-qAt',
            '-v','ON_ERROR_STOP=1','-U',role,'-d','vahan'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            holder.stdin.write("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
                "SELECT json_build_object('snapshot',pg_export_snapshot(),'database',json_build_object("
                "'schemaVersion',(SELECT version_num FROM alembic_version),'counts',json_build_object("
                "'jobs',(SELECT count(*) FROM jobs),'main_reports',(SELECT count(*) FROM main_reports),"
                "'users',(SELECT count(*) FROM users),'stored_files',(SELECT count(*) FROM stored_files))));\n")
            holder.stdin.flush()
            line=holder.stdout.readline()
            if not line: raise RuntimeError('Could not obtain a consistent database snapshot.')
            snapshot=json.loads(line)
            with dump.open('wb') as output:
                subprocess.run([*command,'exec','-T','postgres','pg_dump','-U',role,'-d','vahan','-Fc',
                                '--snapshot',snapshot['snapshot']],
                               stdout=output, stderr=subprocess.DEVNULL, check=True)
        finally:
            if holder.poll() is None:
                holder.stdin.write('ROLLBACK;\n\\q\n'); holder.stdin.flush()
            holder.stdin.close()
            holder.wait(timeout=15)
        restrict_permissions(dump)
        shutil.copyfile(env, folder/'.docker.env'); restrict_permissions(folder/'.docker.env')
        manifest = {'version':1,'tenantId':tenant,'createdAt':datetime.now(timezone.utc).isoformat(),
                    'database':snapshot['database'],'sha256':{}}
        for file in ['database.dump','.docker.env']:
            with (folder/file).open('rb') as reader: manifest['sha256'][file] = hash_stream(reader)
        (folder/'manifest.json').write_text(json.dumps(manifest))
        temporary = target/'backup.age.partial'
        process = subprocess.Popen(['age','-r',recipient,'-o',str(temporary)],stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdin, mode='w|') as archive:
                for file in ['database.dump','.docker.env','manifest.json']:
                    archive.add(folder/file, arcname=file, recursive=False)
            process.stdin.close(); process.stderr.read()
            if process.wait(): raise RuntimeError('Backup encryption failed.')
            verified = decrypt_verify(temporary,key,folder)
            final = target/'backup.age'; temporary.replace(final); restrict_permissions(final)
            with final.open('rb') as reader: encrypted_hash=hash_stream(reader)
            (target/'complete.json').write_text(json.dumps({'tenantId':tenant,'createdAt':manifest['createdAt'],
                'encryptedSha256':encrypted_hash,'database':verified['database'],'verified':True},indent=2)+'\n')
            restrict_permissions(target/'complete.json')
            print(json.dumps({'backup':str(final),'tenantId':tenant,'verified':True}))
            return final
        except Exception:
            process.kill(); process.wait(); temporary.unlink(missing_ok=True)
            raise


def verify(backup,key,restore=False):
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='vahan-restore-check-') as name:
        folder=Path(name); manifest=decrypt_verify(Path(backup),Path(key),folder)
        result={'authenticated':True,'tenantId':manifest['tenantId'],'manifest':manifest['database'],'restored':False}
        if restore:
            command=compose(ROOT/'.docker.env')
            running=subprocess.run([*command,'ps','-q','postgres'],capture_output=True,text=True,check=True).stdout.strip()
            image=subprocess.run(['docker','inspect','--format','{{.Image}}',running],capture_output=True,text=True,check=True).stdout.strip()
            container='vahan-restore-test-'+secrets.token_hex(6)
            environment=dict(os.environ); environment['POSTGRES_PASSWORD']=secrets.token_hex(32)
            try:
                subprocess.run(['docker','run','-d','--name',container,'--network','none','--memory','1g',
                    '--cpus','1','--pids-limit','128','--env','POSTGRES_PASSWORD',image],
                    env=environment,capture_output=True,check=True)
                for _ in range(60):
                    ready=subprocess.run(['docker','exec',container,'pg_isready','-U','postgres'],capture_output=True)
                    main=subprocess.run(['docker','exec',container,'cat','/proc/1/comm'],capture_output=True,text=True)
                    if ready.returncode==0 and main.stdout.strip()=='postgres':break
                    time.sleep(1)
                else:raise RuntimeError('Restore verification database did not become ready.')
                with tarfile.open(folder/'verified.tar') as archive:
                    with archive.extractfile('database.dump') as dump:
                        process=subprocess.Popen(['docker','exec','-i',container,'pg_restore','-U','postgres','-d','postgres',
                            '--exit-on-error','--no-owner','--no-privileges'],stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                        while data:=dump.read(1024*1024):process.stdin.write(data)
                        process.stdin.close()
                        if process.wait(timeout=1200):raise RuntimeError('Restore verification failed.')
                sql="SELECT json_build_object('jobs',(SELECT count(*) FROM jobs),'main_reports',(SELECT count(*) FROM main_reports),'users',(SELECT count(*) FROM users),'stored_files',(SELECT count(*) FROM stored_files))"
                actual=json.loads(subprocess.run(['docker','exec',container,'psql','-X','-U','postgres','-d','postgres','-Atc',sql],
                                                capture_output=True,text=True,check=True).stdout)
                if actual!=manifest['database']['counts']:raise RuntimeError('Restored counts do not match the backup manifest.')
                result['restored']=True;result['counts']=actual
            finally:
                subprocess.run(['docker','rm','-f','-v',container],capture_output=True)
        print(json.dumps(result));return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.docker.env')
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--verify',type=Path)
    parser.add_argument('--identity',type=Path)
    parser.add_argument('--restore-test',action='store_true')
    args=parser.parse_args()
    if args.verify:
        key=args.identity or Path(read_env(args.env_file)['VAHAN_BACKUP_IDENTITY_FILE'])
        key=(key if key.is_absolute() else ROOT/key).resolve()
        verify(args.verify,key,args.restore_test)
    else:create(args.env_file,args.destination)
