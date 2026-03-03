from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import get_current_user, lecturer_or_admin
from ..database import get_db
from ..models import AuditAction, Exam, ReviewDecision, ReviewStatus, Role, SimilarityPair, User
from ..schemas import PairOut, ReviewCreate, ReviewOut
from ..services.audit import log as audit

router = APIRouter(prefix="/reports", tags=["reports"])


def _assert_exam_access(exam_id: int, user: User, db: Session) -> Exam:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if user.role == Role.lecturer and exam.course.lecturer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your exam")
    return exam


@router.get("/{exam_id}/pairs", response_model=list[PairOut])
def get_pairs(
    exam_id: int,
    request: Request,
    min_score: float = 0.0,
    db: Session = Depends(get_db),
    user: User = Depends(lecturer_or_admin),
):
    _assert_exam_access(exam_id, user, db)
    audit(db, AuditAction.report_viewed, user_id=user.id, target_id=exam_id, target_type="exam",
          ip_address=request.client.host if request.client else None)

    from ..models import Submission
    sub_ids = [s.id for s in db.query(Submission.id).filter_by(exam_id=exam_id)]
    return (
        db.query(SimilarityPair)
        .filter(
            SimilarityPair.submission_a_id.in_(sub_ids),
            SimilarityPair.similarity_score >= min_score,
        )
        .order_by(SimilarityPair.similarity_score.desc())
        .all()
    )


@router.get("/pairs/{pair_id}", response_model=PairOut)
def get_pair(pair_id: int, db: Session = Depends(get_db), user: User = Depends(lecturer_or_admin)):
    pair = db.get(SimilarityPair, pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Pair not found")
    return pair


@router.post("/pairs/{pair_id}/review", response_model=ReviewOut)
def submit_review(
    pair_id: int,
    request: Request,
    body: ReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(lecturer_or_admin),
):
    pair = db.get(SimilarityPair, pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Pair not found")

    review = db.query(ReviewDecision).filter_by(pair_id=pair_id).first()
    if review:
        review.status = body.status
        review.notes = body.notes
        review.reviewer_id = user.id
    else:
        review = ReviewDecision(pair_id=pair_id, reviewer_id=user.id, **body.model_dump())
        db.add(review)
    db.commit()

    audit(db, AuditAction.review_decision, user_id=user.id, target_id=pair_id, target_type="pair",
          detail={"status": body.status}, ip_address=request.client.host if request.client else None)

    db.refresh(review)
    return review