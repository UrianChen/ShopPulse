"""Retention for opt-in debug captures stored on agent runs."""

from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import session as db_module
from app.db.models import AgentRun, now


def purge_debug():
    cutoff = now() - timedelta(days=settings().agent_debug_retention_days)
    with Session(db_module.engine()) as db, db.begin():
        result = db.execute(
            update(AgentRun)
            .where(AgentRun.debug.is_not(None), AgentRun.created_at < cutoff)
            .values(debug=None)
        )
        return result.rowcount
