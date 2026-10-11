from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db.models import Workspace
from app.db.session import db_session


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: UUID


def require_origin(request: Request):
    if request.headers.get("origin") != settings().origin:
        raise AppError(403, "ORIGIN_REJECTED", "请求来源不受信任，请从应用页面访问。")


def current_workspace(db: Session = Depends(db_session)) -> WorkspaceContext:
    workspace_id = db.scalar(select(Workspace.id).where(Workspace.slug == "default"))
    if workspace_id is None:
        # Concurrent first requests converge on the unique default shop.
        db.execute(
            insert(Workspace)
            .values(slug="default", name="我的店铺", timezone=settings().app_timezone)
            .on_conflict_do_nothing(index_elements=[Workspace.slug])
        )
        db.commit()
        workspace_id = db.scalar(select(Workspace.id).where(Workspace.slug == "default"))
    return WorkspaceContext(workspace_id)


def mutation_workspace(
    _: None = Depends(require_origin),
    workspace: WorkspaceContext = Depends(current_workspace),
) -> WorkspaceContext:
    return workspace


def envelope(request: Request, data):
    return {"data": data, "meta": {"request_id": request.state.request_id}}
