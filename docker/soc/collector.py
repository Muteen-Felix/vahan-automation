"""Internal append-only SOC receiver. No application-accessible read/delete API."""
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from uuid import UUID

DATA = Path(os.environ.get('SOC_DATA_DIR', '/data'))
TENANT = os.environ.get('VAHAN_TENANT_ID', 'legacy')
KEY = os.environ.get('VAHAN_SOC_INGEST_KEY', '')
BACKUP_KEY = os.environ.get('VAHAN_SOC_BACKUP_KEY', '')
LOCK = threading.Lock()
STARTED = time.time()


def append(name, value):
    day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    path = DATA / f'{name}-{day}.jsonl'
    with path.open('a', encoding='utf-8') as output:
        os.chmod(path, 0o600)
        output.write(json.dumps(value, ensure_ascii=True) + '\n')
        output.flush()
        os.fsync(output.fileno())


def store(value):
    with LOCK, sqlite3.connect(DATA / 'events.sqlite') as connection:
        os.chmod(DATA / 'events.sqlite', 0o600)
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('CREATE TABLE IF NOT EXISTS events '
            '(id TEXT PRIMARY KEY, received REAL NOT NULL, actor TEXT, event TEXT NOT NULL, body TEXT NOT NULL)')
        if connection.execute('SELECT 1 FROM events WHERE id=?', (value['id'],)).fetchone():
            return
        timestamp = time.time()
        connection.execute('INSERT INTO events VALUES(?,?,?,?,?)',
            (value['id'], timestamp, value.get('actor'), value['event'], json.dumps(value)))
        append('events', value)
        rule = None
        if value['event'] == 'auth.login_failed':
            count = connection.execute('SELECT count(*) FROM events WHERE actor=? AND event=? AND received>?',
                (value.get('actor'), 'auth.login_failed', timestamp - 600)).fetchone()[0]
            if count >= 5:
                rule = 'repeated-login-failure'
        elif value['event'] == 'data.export':
            count = connection.execute('SELECT count(*) FROM events WHERE actor=? AND event=? AND received>?',
                (value.get('actor'), 'data.export', timestamp - 60)).fetchone()[0]
            if count >= 3:
                rule = 'frequent-data-export'
        elif value['event'] in {'user.password_reset', 'security.worker_denied', 'backup.failed'}:
            rule = 'privileged-security-change'
        elif value['event'] == 'http.mutation' and value.get('payload', {}).get('path', '').startswith('/api/users'):
            rule = 'identity-administration'
        elif value['event'] == 'http.denied' and value.get('payload', {}).get('statusCode') == 429:
            rule = 'request-rate-limit'
        if rule:
            alert = {'timestamp': datetime.now(timezone.utc).isoformat(), 'tenantId': TENANT,
                     'event': 'soc.alert', 'rule': rule, 'severity': 'high',
                     'sourceEventId': value['id'], 'actor': value.get('actor')}
            append('alerts', alert)
            print(json.dumps(alert), flush=True)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/health':
            return self.reply(200, {'status': 'ok'})
        self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path != '/events':
            return self.reply(404, {'error': 'Not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024:
                return self.reply(413, {'error': 'Invalid event size'})
            body = self.rfile.read(size)
            source='backup' if self.headers.get('X-SOC-Source')=='backup' else 'api'
            key=BACKUP_KEY if source=='backup' else KEY
            if len(key)<32:return self.reply(401,{'error':'Unauthorized'})
            expected = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(self.headers.get('X-SOC-Signature', ''), expected):
                return self.reply(401, {'error': 'Unauthorized'})
            value = json.loads(body)
            UUID(value['id'])
            if value.get('tenantId') != TENANT or not isinstance(value.get('event'), str) or len(value['event']) > 128:
                return self.reply(403, {'error': 'Invalid tenant event'})
            if source=='backup' and not value['event'].startswith('backup.'):
                return self.reply(403,{'error':'Publisher cannot impersonate the API'})
            value['service']=source
            store(value)
            self.reply(202, {'accepted': True})
        except (ValueError, KeyError, TypeError):
            self.reply(400, {'error': 'Invalid event'})
        except Exception:
            self.reply(503, {'error': 'Event persistence unavailable'})

    def log_message(self, *_args):
        pass


def watchdog():
    alerted=set()
    while True:
        time.sleep(30)
        try:
            with LOCK,sqlite3.connect(DATA/'events.sqlite') as connection:
                for event,seconds,rule in [('service.heartbeat',120,'api-heartbeat-missing'),
                    ('backup.completed',3720,'backup-stale')]:
                    row=connection.execute('SELECT max(received) FROM events WHERE event=?',(event,)).fetchone()
                    stale=time.time()-(row[0] or STARTED)>seconds
                    if stale and rule not in alerted:
                        append('alerts',{'timestamp':datetime.now(timezone.utc).isoformat(),'tenantId':TENANT,
                            'event':'soc.alert','rule':rule,'severity':'high'})
                        print(json.dumps({'event':'soc.alert','rule':rule,'tenantId':TENANT}),flush=True)
                        alerted.add(rule)
                    elif not stale:alerted.discard(rule)
        except Exception:
            pass


if __name__ == '__main__':
    if len(KEY) < 32:
        raise SystemExit('Configure a private SOC ingestion key.')
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(DATA, 0o700)
    threading.Thread(target=watchdog,daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', 3100), Handler).serve_forever()
