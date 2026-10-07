"""Internal Docker controller: only start/stop this project's ten crawler services."""
import hmac
import http.client
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlencode

PROJECT = 'vahan-automation'
SERVICES = ['runner', *[f'runner-{number}' for number in range(2, 11)]]

class ControlError(Exception):
    pass

class DockerConnection(http.client.HTTPConnection):
    def __init__(self, path='/var/run/docker.sock'):
        super().__init__('localhost', timeout=30)
        self.path = path
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)

class DockerEngine:
    def request(self, method, path):
        connection = DockerConnection()
        try:
            connection.request(method, path)
            response = connection.getresponse(); data = response.read()
            if response.status not in (200, 204, 304):
                raise ControlError(f'Docker request failed (HTTP {response.status}).')
            return json.loads(data) if data else None
        finally:
            connection.close()
    def containers(self):
        filters = json.dumps({'label': [f'com.docker.compose.project={PROJECT}']})
        return self.request('GET', '/containers/json?' + urlencode({'all': 'true', 'filters': filters}))
    def inspect(self, identifier):
        return self.request('GET', '/containers/' + quote(identifier, safe='') + '/json')
    def start(self, identifier):
        self.request('POST', '/containers/' + quote(identifier, safe='') + '/start')
    def stop(self, identifier):
        self.request('POST', '/containers/' + quote(identifier, safe='') + '/stop?t=20')

def worker_idle(service):
    connection = http.client.HTTPConnection(service, 3001, timeout=3)
    try:
        connection.request('GET', '/health')
        response = connection.getresponse()
        payload = json.loads(response.read())
        return payload.get('activeJobId') is None and not payload.get('optionsBusy', False)
    except (OSError, ValueError, http.client.HTTPException):
        return False  # Never stop a running browser with unknown activity.
    finally:
        connection.close()

class WorkerController:
    def __init__(self, engine=None, idle=worker_idle):
        self.engine = engine or DockerEngine()
        self.idle = idle
        self.lock = threading.Lock()
    def managed(self):
        result = {}
        for container in self.engine.containers():
            labels = container.get('Labels') or {}
            service = labels.get('com.docker.compose.service')
            if (labels.get('com.docker.compose.project') != PROJECT or service not in SERVICES
                    or labels.get('com.docker.compose.oneoff', '').lower() == 'true'):
                continue
            if service in result:
                raise ControlError(f'Multiple containers found for {service}.')
            result[service] = container
        return result
    def state(self):
        containers = self.managed()
        workers = [{'number': number, 'service': service,
            'running': containers.get(service, {}).get('State') == 'running'}
            for number, service in enumerate(SERVICES, 1)]
        return {'runningCount': sum(worker['running'] for worker in workers), 'workers': workers}
    def apply(self, count):
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
            raise ControlError('Choose between 1 and 10 worker containers.')
        with self.lock:
            containers = self.managed()
            missing = [service for service in SERVICES[:count] if service not in containers]
            if missing:
                raise ControlError('Create crawler containers with run-vahan-rpa.sh first.')
            stopping = [service for service in SERVICES[count:]
                if containers.get(service, {}).get('State') == 'running']
            # Check the entire stop set before touching any container.
            if any(not self.idle(service) for service in stopping):
                raise ControlError('A worker is still busy. Stop its job before changing containers.')
            for service in stopping:
                container = self.engine.inspect(containers[service]['Id'])
                if (container['Config']['Labels'].get('com.docker.compose.project') != PROJECT
                        or container['Config']['Labels'].get('com.docker.compose.service') != service):
                    raise ControlError('Container ownership changed; retry.')
                self.engine.stop(containers[service]['Id'])
            for service in SERVICES[:count]:
                if containers[service].get('State') != 'running':
                    self.engine.start(containers[service]['Id'])
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                ready = all(self.engine.inspect(containers[service]['Id'])['State']
                    .get('Health', {}).get('Status') == 'healthy' for service in SERVICES[:count])
                if ready:
                    state = self.state()
                    if state['runningCount'] == count:
                        return state
                time.sleep(.25)
            raise ControlError('Selected worker containers did not become healthy in time.')

def serve():
    token = os.environ.get('VAHAN_API_RUNNER_TOKEN', '')
    if len(token) < 24 or token == 'change-me':
        raise RuntimeError('Configure a private controller token.')
    controller = WorkerController()
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        def authorized(self):
            return hmac.compare_digest(self.headers.get('X-Worker-Control-Token', '').encode(), token.encode())
        def do_GET(self):
            if self.path == '/health':
                try:
                    controller.engine.request('GET', '/version'); self.reply(200, {'status': 'ok'})
                except Exception:
                    self.reply(503, {'error': 'Docker engine unavailable.'})
                return
            if not self.authorized(): self.reply(401, {'error': 'Unauthorized.'}); return
            if self.path != '/workers': self.reply(404, {'error': 'Not found.'}); return
            try: self.reply(200, controller.state())
            except ControlError as error: self.reply(503, {'error': str(error)})
            except (OSError, http.client.HTTPException): self.reply(503, {'error': 'Docker engine unavailable.'})
        def do_POST(self):
            if not self.authorized(): self.reply(401, {'error': 'Unauthorized.'}); return
            if self.path != '/workers': self.reply(404, {'error': 'Not found.'}); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024: raise ControlError('Invalid request size.')
                count = json.loads(self.rfile.read(size))['count']
                self.reply(200, controller.apply(count))
            except (ValueError, KeyError, ControlError) as error:
                self.reply(409, {'error': str(error)})
            except (OSError, http.client.HTTPException):
                self.reply(503, {'error': 'Docker engine unavailable.'})
        def log_message(self, *_args):
            pass
    ThreadingHTTPServer(('0.0.0.0', 3002), Handler).serve_forever()

if __name__ == '__main__':
    serve()
