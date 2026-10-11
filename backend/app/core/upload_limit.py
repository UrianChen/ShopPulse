"""Bound multipart bodies before Starlette spools files, including chunked requests."""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.core.config import settings


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/v1/uploads":
            return await self.app(scope, receive, send)
        # Allow 1 MiB for multipart headers; the endpoint separately enforces file size.
        limit = (settings().max_upload_mib + 1) * 1024 * 1024
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = limit + 1
        if declared > limit:
            response = JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "FILE_TOO_LARGE",
                        "message": "上传请求超过大小限制。",
                        "retryable": False,
                    },
                    "meta": {"request_id": scope.get("state", {}).get("request_id", "unknown")},
                },
            )
            return await response(scope, receive, send)
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    raise HTTPException(413, "上传请求超过大小限制。")
            return message

        return await self.app(scope, bounded_receive, send)
