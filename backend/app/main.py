import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app import __version__
from app.api.automation import router as automation_router
from app.api.exports import router as exports_router
from app.api.imports import router as import_router
from app.api.metrics import router as metrics_router
from app.api.model_configs import router as model_router
from app.api.operations import router as operations_router
from app.api.reports import router as reports_router
from app.api.routes import router
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.upload_limit import UploadLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings().validate_secrets()
    configure_logging(settings().log_level)
    yield


app = FastAPI(title="ShopPulse API", version=__version__, lifespan=lifespan)
app.include_router(router)
app.include_router(import_router)
app.include_router(metrics_router)
app.include_router(model_router)
app.include_router(reports_router)
app.include_router(exports_router)
app.include_router(operations_router)
app.include_router(automation_router)
app.add_middleware(UploadLimitMiddleware)


def error_response(request: Request, status: int, code: str, message: str, retryable=False):
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "retryable": retryable},
            "meta": {"request_id": getattr(request.state, "request_id", "unknown")},
        },
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    started = time.monotonic()
    try:
        request_id = str(uuid.UUID(request.headers.get("x-request-id", "")))
    except ValueError:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception:
        response = error_response(request, 500, "INTERNAL_ERROR", "服务异常，请稍后重试。", True)
    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    logging.getLogger("shoppulse").info(
        "request_completed",
        extra={
            "event": "request_completed",
            "request_id": request_id,
            "status": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return response


@app.exception_handler(AppError)
async def application_error(request: Request, exc: AppError):
    return error_response(request, exc.status, exc.code, exc.message, exc.retryable)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Pydantic errors can contain submitted API keys. Never serialize exc.errors().
    return error_response(request, 422, "VALIDATION_ERROR", "请求字段不符合要求，请检查输入。")


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    return error_response(request, 503, "DATABASE_UNAVAILABLE", "数据库暂不可用。", True)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 413:
        return error_response(request, 413, "FILE_TOO_LARGE", "上传请求超过大小限制。")
    return error_response(request, exc.status_code, "HTTP_ERROR", "请求的资源或方法不可用。")
