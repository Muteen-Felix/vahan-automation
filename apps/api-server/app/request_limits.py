"""Bound streaming request bodies before JSON/multipart parsing."""
from starlette.exceptions import HTTPException


class RequestLimits:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        multipart = headers.get(b'content-type', b'').startswith(b'multipart/form-data')
        limit = 52 * 1024 * 1024 if multipart else 8 * 1024 * 1024
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            if message['type'] == 'http.request':
                total += len(message.get('body', b''))
                if total > limit:
                    raise HTTPException(413, 'Request body exceeds the allowed size.')
            return message
        await self.app(scope, bounded_receive, send)
