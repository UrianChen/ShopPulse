from app.db.models import AuditEvent


def audit(db, actor, action, target, details=None):
    # Only explicitly constructed metadata; never serialize request bodies or credentials.
    db.add(
        AuditEvent(
            workspace_id=actor.workspace_id,
            action=action,
            target_id=str(target),
            details=details or {},
        )
    )
