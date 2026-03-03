from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import AuditAction, Exam, Role, SimilarityPair, Submission, User
from ..services.audit import log as audit

router = APIRouter(prefix="/student", tags=["student"])
templates = Jinja2Templates(directory="templates")


@router.get("/dashboard", response_class=HTMLResponse)
def student_dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if user.role != Role.student:
        raise HTTPException(status_code=403, detail="Students only")

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    open_exams = db.query(Exam).filter(Exam.opens_at <= now, Exam.closes_at >= now).all()
    submissions = (
        db.query(Submission)
        .filter_by(student_id=user.id)
        .order_by(Submission.uploaded_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        "student/dashboard.html",
        {
            "request": request,
            "user": user,
            "open_exams": open_exams,
            "submissions": submissions,
        },
    )


@router.get("/submissions/{submission_id}", response_class=HTMLResponse)
def submission_detail(
    submission_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if user.role != Role.student:
        raise HTTPException(status_code=403, detail="Students only")

    sub = db.get(Submission, submission_id)
    if not sub or sub.student_id != user.id:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Find this submission's worst pair for display context
    pairs = (
        db.query(SimilarityPair)
        .filter(
            (SimilarityPair.submission_a_id == submission_id)
            | (SimilarityPair.submission_b_id == submission_id)
        )
        .order_by(SimilarityPair.similarity_score.desc())
        .all()
    )

    audit(
        db,
        AuditAction.report_viewed,
        user_id=user.id,
        target_id=submission_id,
        target_type="submission",
    )

    return templates.TemplateResponse(
        "student/submission.html",
        {
            "request": request,
            "user": user,
            "sub": sub,
            "exam": sub.exam,
            "pairs": pairs,
        },
    )
