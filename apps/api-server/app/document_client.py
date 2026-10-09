"""Call the isolated document service with bounded concurrency and deadlines."""
import asyncio
import json
import os
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from urllib.parse import quote
from app.config import settings

_slots = asyncio.Semaphore(1)


async def document(operation, content, name='report.xlsx'):
    endpoint = os.getenv('VAHAN_DOCUMENT_SERVICE_URL', '')
    if not endpoint:
        if settings.production:
            raise ValueError('Production document service is unavailable.')
        if operation == 'extract':
            from app.repositories.file_store import extract_file
            return await asyncio.to_thread(extract_file, content, name)
        from app.repositories.annual_export import build_workbook
        value = json.loads(content)
        return await asyncio.to_thread(build_workbook, value['rows'], value['year'], value.get('state',''), value.get('rto',''))
    def send():
        request = Request(endpoint.rstrip('/') + '/' + operation, data=content,
                          headers={'X-Document-Name': quote(name, safe=''), 'Content-Type':'application/octet-stream'})
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=settings.parser_timeout_seconds + 10) as response:
                data = response.read(256 * 1024 * 1024 + 1)
                if len(data) > 256 * 1024 * 1024:
                    raise ValueError('Document response exceeds the allowed size.')
        except HTTPError as error:
            raise ValueError(f'Document processor rejected the request (HTTP {error.code}).') from None
        if operation == 'extract':
            value = json.loads(data)
            return value['rows'], value['info']
        from app.repositories.annual_export import report_title
        import re
        value = json.loads(content)
        filename = re.sub(r'[\\/*?:"<>|\r\n\t]', '_', report_title(value['rows'],value['year'],value.get('state',''),value.get('rto',''))).strip('. ')[:200] + '.xlsx'
        return data, filename
    async with _slots:
        return await asyncio.to_thread(send)
