import json
import os
import subprocess
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db import session as db_module
from app.db.models import Job, ModelConfig, now
from app.jobs.queue import owned
from app.providers.adapter import failure
from app.providers.credentials import decrypt
from app.providers.egress import ProviderError


def probe(config, key):
    env = os.environ.copy()
    env["MODEL_ALLOWED_ORIGINS"] = json.dumps(settings().model_allowed_origins)
    process = subprocess.Popen(
        [sys.executable, "-m", "app.providers.runner"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        output, _ = process.communicate(
            json.dumps({"config": config, "key": key}).encode(), timeout=90
        )
        if process.returncode != 0:
            raise ProviderError("NETWORK_ERROR")
        return json.loads(output)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise ProviderError("TIMEOUT") from None


def execute(job):
    with Session(db_module.engine()) as db:
        item = db.scalar(
            select(ModelConfig).where(
                ModelConfig.id == uuid.UUID(job.payload["config_id"]),
                ModelConfig.workspace_id == job.workspace_id,
            )
        )
        if not item or item.revision != job.payload["revision"]:
            raise RuntimeError("Stale configuration")
        config = {
            field: getattr(item, field)
            for field in ("base_url", "model_name", "timeout_seconds", "token_limit_parameter")
        }
        try:
            key = decrypt(item)
        except AppError:
            key = None
    try:
        if key is None:
            raise ProviderError("CREDENTIAL_UNAVAILABLE")
        result = probe(config, key)
    except ProviderError as error:
        result = {"usable": False, "strategy": "unavailable", "stages": {"basic": failure(error)}}
    finally:
        key = None
    with Session(db_module.engine()) as db, db.begin():
        active = db.scalar(select(Job).where(*owned(job)).with_for_update())
        if not active:
            return
        item = db.get(ModelConfig, uuid.UUID(job.payload["config_id"]), with_for_update=True)
        if item and item.revision == job.payload["revision"] and item.test_job_id == job.id:
            item.capabilities, item.tested_at = result, now()
        active.result = {
            "config_id": job.payload["config_id"],
            "revision": job.payload["revision"],
            **result,
        }
        active.status = "succeeded" if result["usable"] else "failed"
        active.error_code = None if result["usable"] else result["stages"]["basic"]["code"]
        active.updated_at, active.lease_expires_at = now(), None
