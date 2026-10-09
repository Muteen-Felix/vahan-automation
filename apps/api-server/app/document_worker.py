"""Internal document processor; no DB/runner/signing credentials in its container."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import unquote


def run_operation(operation, source, output, name=''):
    # This subprocess can be killed on timeout; cancelling an asyncio thread
    # cannot stop a parser that is still consuming CPU/memory.
    environment = {key: os.environ[key] for key in ['PATH', 'LANG'] if key in os.environ}
    result = subprocess.run([sys.executable, '-m', 'app.document_worker', '--child', operation,
                            str(source), str(output), name], env=environment,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=int(os.getenv('VAHAN_PARSER_TIMEOUT_SECONDS', '120')))
    if result.returncode:
        raise ValueError('Invalid document or document processing limit exceeded.')


def child(operation, source, output, name):
    if sys.platform.startswith('linux'):
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1024 ** 3, 1024 ** 3))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    if operation == 'extract':
        from app.repositories.file_store import extract_file
        rows, info = extract_file(Path(source).read_bytes(), name)
        Path(output).write_text(json.dumps({'rows': rows, 'info': info}), encoding='utf-8')
    elif operation == 'export':
        from app.repositories.annual_export import build_workbook
        value = json.loads(Path(source).read_bytes())
        if len(value['rows']) > int(os.getenv('VAHAN_MAX_EXPORT_ROWS', '100000')):
            raise ValueError('Export row limit exceeded.')
        content, _ = build_workbook(value['rows'], value['year'], value.get('state', ''), value.get('rto', ''))
        Path(output).write_bytes(content)
    else:
        raise ValueError('Invalid operation.')


def serve():
    slots = threading.BoundedSemaphore(1)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup(); self.connection.settimeout(30)
        def do_GET(self):
            self.send_response(200 if self.path == '/health' else 404); self.end_headers()
        def do_POST(self):
            if self.path not in {'/extract', '/export'}:
                self.send_error(404); return
            if not slots.acquire(blocking=False):
                self.send_error(429, 'Document processor is busy'); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 128 * 1024 * 1024:
                    self.send_error(413); return
                with tempfile.TemporaryDirectory(prefix='document-') as folder:
                    source, output = Path(folder)/'input', Path(folder)/'output'
                    with source.open('wb') as target:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(256 * 1024, remaining))
                            if not chunk: raise ValueError('Incomplete document')
                            target.write(chunk); remaining -= len(chunk)
                    run_operation(self.path[1:], source, output, unquote(self.headers.get('X-Document-Name', 'report.xlsx')))
                    size = output.stat().st_size
                    self.send_response(200); self.send_header('Content-Length', str(size)); self.end_headers()
                    with output.open('rb') as reader:
                        while data := reader.read(256 * 1024): self.wfile.write(data)
            except subprocess.TimeoutExpired:
                self.send_error(408, 'Document processing timed out')
            except Exception:
                self.send_error(400, 'Invalid document or processing limit exceeded')
            finally:
                slots.release()
        def log_message(self, *_args): pass
    ThreadingHTTPServer(('0.0.0.0', 3101), Handler).serve_forever()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(*sys.argv[2:])
    else:
        serve()
