import json

from sqlalchemy.orm import Session

from ..models import AuditAction, AuditLog


def log(
    db: Session,
    action: AuditAction,
    user_id: int | None = None,
    target_id: int | None = None,
    target_type: str | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            target_id=target_id,
            target_type=target_type,
            detail=json.dumps(detail) if detail else None,
            ip_address=ip_address,
        )
    )
    db.commit()
