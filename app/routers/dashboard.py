from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import lecturer_or_admin
from ..database import get_db
from ..models import (
    AuditAction, Course, Exam, PlagiarismJob, ReviewDecision,
    ReviewStatus, SimilarityPair, Submission, User,
)
from ..services.audit import log as audit

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request, db: Session = Depends(get_db), user: User = Depends(lecturer_or_admin)):
    courses = db.query(Course).filter_by(lecturer_id=user.id).all()
    return templates.TemplateResponse("dashboard/home.html", {
        "request": request, "user": user, "courses": courses,
    })


@router.get("/exams/{exam_id}", response_class=HTMLResponse)
def exam_detail(
    exam_id: int,
    request: Request,
    min_score: float = 0.3,
    db: Session = Depends(get_db),
    user: User = Depends(lecturer_or_admin),
):
    exam = db.get(Exam, exam_id)
    if not exam or exam.course.lecturer_id != user.id:
        raise HTTPException(status_code=404)

    audit(db, AuditAction.report_viewed, user_id=user.id, target_id=exam_id, target_type="exam",
          ip_address=request.client.host if request.client else None)

    job     = db.query(PlagiarismJob).filter_by(exam_id=exam_id).first()
    sub_ids = [s.id for s in db.query(Submission.id).filter_by(exam_id=exam_id)]
    pairs   = (
        db.query(SimilarityPair)
        .filter(
            SimilarityPair.submission_a_id.in_(sub_ids),
            SimilarityPair.similarity_score >= min_score,
        )
        .order_by(SimilarityPair.similarity_score.desc())
        .all()
    ) if sub_ids else []

    return templates.TemplateResponse("dashboard/exam.html", {
        "request": request, "exam": exam, "job": job,
        "pairs": pairs, "min_score": min_score, "user": user,
    })


@router.get("/pairs/{pair_id}", response_class=HTMLResponse)
def pair_detail(pair_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(lecturer_or_admin)):
    pair = db.get(SimilarityPair, pair_id)
    if not pair:
        raise HTTPException(status_code=404)

    sub_a = db.get(Submission, pair.submission_a_id)
    sub_b = db.get(Submission, pair.submission_b_id)

    highlights_a = _highlight(sub_a.extracted_text or "", [(f.start_a, f.end_a) for f in pair.fragments])
    highlights_b = _highlight(sub_b.extracted_text or "", [(f.start_b, f.end_b) for f in pair.fragments])

    return templates.TemplateResponse("dashboard/pair.html", {
        "request": request, "pair": pair,
        "sub_a": sub_a, "sub_b": sub_b,
        "highlights_a": highlights_a, "highlights_b": highlights_b,
        "review_statuses": [s.value for s in ReviewStatus],
    })


@router.post("/pairs/{pair_id}/review", response_class=HTMLResponse)
async def update_review(
    pair_id: int, request: Request,
    db: Session = Depends(get_db), user: User = Depends(lecturer_or_admin),
):
    form   = await request.form()
    status = form.get("status")
    notes  = form.get("notes", "")

    pair   = db.get(SimilarityPair, pair_id)
    review = db.query(ReviewDecision).filter_by(pair_id=pair_id).first()
    if review:
        review.status = status
        review.notes  = notes
        review.reviewer_id = user.id
    else:
        review = ReviewDecision(pair_id=pair_id, reviewer_id=user.id, status=status, notes=notes)
        db.add(review)
    db.commit()
    audit(db, AuditAction.review_decision, user_id=user.id, target_id=pair_id, target_type="pair",
          detail={"status": status})
    db.refresh(review)

    return templates.TemplateResponse("dashboard/fragments/review_badge.html", {
        "request": request, "review": review, "pair_id": pair_id,
    })


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