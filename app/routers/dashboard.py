from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import lecturer_or_admin
from ..database import get_db
from ..models import (
    AuditAction,
    Course,
    CourseDepartment,
    Exam,
    PlagiarismJob,
    ReviewDecision,
    ReviewStatus,
    Role,
    SimilarityPair,
    Submission,
    User,
)
from ..services.audit import log as audit

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def dashboard_home(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
):
    courses = (
        db.query(Course).all()
        if user.role == Role.admin
        else db.query(Course).filter_by(lecturer_id=user.id).all()
    )
    return templates.TemplateResponse(
        "dashboard/home.html",
        {"request": request, "user": user, "courses": courses},
    )

# --- Exam creation ---


@router.get("/exams/new", response_class=HTMLResponse)
def new_exam_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
    course_id: int | None = None,
):
    courses = (
        db.query(Course).all()
        if user.role == Role.admin
        else db.query(Course).filter_by(lecturer_id=user.id).all()
    )
    return templates.TemplateResponse(
        "dashboard/exam_new.html",
        {
            "request": request,
            "user": user,
            "courses": courses,
            "error": None,
            "preselect_course": course_id,
        },
    )


@router.post("/exams/new", response_class=HTMLResponse)
async def create_exam(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
    course_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    opens_at: str = Form(...),
    closes_at: str = Form(...),
    allowed_formats: str = Form("pdf,docx,txt"),
    max_file_mb: int = Form(10),
    similarity_threshold: float = Form(0.4),
):
    course = db.get(Course, course_id)
    if not course or (user.role == Role.lecturer and course.lecturer_id != user.id):
        raise HTTPException(status_code=403, detail="Not your course")

    try:
        opens = datetime.fromisoformat(opens_at)
        closes = datetime.fromisoformat(closes_at)
    except ValueError:
        courses = (
            db.query(Course).all()
            if user.role == Role.admin
            else db.query(Course).filter_by(lecturer_id=user.id).all()
        )
        return templates.TemplateResponse(
            "dashboard/exam_new.html",
            {"request": request, "user": user, "courses": courses, "error": "Invalid date format."},
            status_code=400,
        )

    if closes <= opens:
        courses = (
            db.query(Course).all()
            if user.role == Role.admin
            else db.query(Course).filter_by(lecturer_id=user.id).all()
        )
        return templates.TemplateResponse(
            "dashboard/exam_new.html",
            {
                "request": request,
                "user": user,
                "courses": courses,
                "error": "Closing time must be after opening time.",
            },
            status_code=400,
        )

    exam = Exam(
        course_id=course_id,
        title=title,
        description=description or None,
        opens_at=opens,
        closes_at=closes,
        allowed_formats=allowed_formats,
        max_file_mb=max_file_mb,
        similarity_threshold=similarity_threshold,
    )
    db.add(exam)
    db.commit()
    audit(db, AuditAction.exam_created, user_id=user.id, target_id=exam.id, target_type="exam")
    return RedirectResponse(url=f"/dashboard/exams/{exam.id}", status_code=303)


# --- Exam detail ---


@router.get("/exams/{exam_id}", response_class=HTMLResponse)
def exam_detail(
    exam_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
    min_score: float = 0.3,
):
    exam = db.get(Exam, exam_id)
    if not exam or (user.role == Role.lecturer and exam.course.lecturer_id != user.id):
        raise HTTPException(status_code=404)

    audit(
        db,
        AuditAction.report_viewed,
        user_id=user.id,
        target_id=exam_id,
        target_type="exam",
        ip_address=request.client.host if request.client else None,
    )

    job = db.query(PlagiarismJob).filter_by(exam_id=exam_id).first()
    submissions = (
        db.query(Submission)
        .filter_by(exam_id=exam_id)
        .order_by(Submission.uploaded_at.desc())
        .all()
    )
    sub_ids = [s.id for s in submissions]
    pairs = (
        db.query(SimilarityPair)
        .filter(
            SimilarityPair.submission_a_id.in_(sub_ids),
            SimilarityPair.similarity_score >= min_score,
        )
        .order_by(SimilarityPair.similarity_score.desc())
        .all()
        if sub_ids
        else []
    )

    return templates.TemplateResponse(
        "dashboard/exam.html",
        {
            "request": request,
            "exam": exam,
            "job": job,
            "submissions": submissions,
            "pairs": pairs,
            "min_score": min_score,
            "user": user,
            "now": datetime.now(UTC).replace(tzinfo=None),
        },
    )


# --- Pair detail ---


@router.get("/pairs/{pair_id}", response_class=HTMLResponse)
def pair_detail(
    pair_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
):
    pair = db.get(SimilarityPair, pair_id)
    if not pair:
        raise HTTPException(status_code=404)

    sub_a = db.get(Submission, pair.submission_a_id)
    sub_b = db.get(Submission, pair.submission_b_id)
    if not sub_a or not sub_b:
        raise HTTPException(status_code=404)

    if user.role == Role.lecturer and sub_a.exam.course.lecturer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your pair")

    highlights_a = _highlight(
        sub_a.extracted_text or "", [(f.start_a, f.end_a) for f in pair.fragments]
    )
    highlights_b = _highlight(
        sub_b.extracted_text or "", [(f.start_b, f.end_b) for f in pair.fragments]
    )

    return templates.TemplateResponse(
        "dashboard/pair.html",
        {
            "request": request,
            "user": user,
            "pair": pair,
            "sub_a": sub_a,
            "sub_b": sub_b,
            "highlights_a": highlights_a,
            "highlights_b": highlights_b,
            "review_statuses": [s.value for s in ReviewStatus],
        },
    )


@router.post("/pairs/{pair_id}/review", response_class=HTMLResponse)
async def update_review(
    pair_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
):
    form = await request.form()
    status = form.get("status")
    notes = form.get("notes", "")

    db.get(SimilarityPair, pair_id)
    review = db.query(ReviewDecision).filter_by(pair_id=pair_id).first()
    if review:
        review.status = status
        review.notes = notes
        review.reviewer_id = user.id
    else:
        review = ReviewDecision(pair_id=pair_id, reviewer_id=user.id, status=status, notes=notes)
        db.add(review)
    db.commit()
    audit(
        db,
        AuditAction.review_decision,
        user_id=user.id,
        target_id=pair_id,
        target_type="pair",
        detail={"status": status},
    )
    db.refresh(review)

    return templates.TemplateResponse(
        "dashboard/fragments/review_badge.html",
        {"request": request, "review": review, "pair_id": pair_id},
    )


def _highlight(text: str, spans: list[tuple[int, int]]) -> list[dict]:
    tokens = text.split()
    matched = set()
    for s, e in spans:
        matched.update(range(s, e))
    segments, i = [], 0
    while i < len(tokens):
        is_match = i in matched
        j = i
        while j < len(tokens) and (j in matched) == is_match:
            j += 1
        segments.append({"text": " ".join(tokens[i:j]), "matched": is_match})
        i = j
    return segments
