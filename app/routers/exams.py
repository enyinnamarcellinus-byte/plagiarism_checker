from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, lecturer_or_admin
from ..database import get_db
from ..models import Exam, Role, User
from ..schemas import ExamCreate, ExamOut

router = APIRouter(prefix="/exams", tags=["exams"])


@router.post("/", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
def create_exam(body: ExamCreate, db: Session = Depends(get_db), user: User = Depends(lecturer_or_admin)):
    exam = Exam(**body.model_dump(), lecturer_id=user.id)
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return exam


@router.get("/", response_model=list[ExamOut])
def list_exams(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role in (Role.lecturer, Role.admin):
        return db.query(Exam).filter(Exam.lecturer_id == user.id).all()
    # students see all currently open exams
    from datetime import datetime, UTC
    now = datetime.now(UTC)
    return db.query(Exam).filter(Exam.opens_at <= now, Exam.closes_at >= now).all()


@router.get("/{exam_id}", response_model=ExamOut)
def get_exam(exam_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if user.role == Role.lecturer and exam.lecturer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your exam")
    return exam


@router.put("/{exam_id}", response_model=ExamOut)
def update_exam(exam_id: int, body: ExamCreate, db: Session = Depends(get_db), user: User = Depends(lecturer_or_admin)):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam.lecturer_id != user.id and user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Not your exam")
    for k, v in body.model_dump().items():
        setattr(exam, k, v)
    db.commit()
    db.refresh(exam)
    return exam


@router.delete("/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exam(exam_id: int, db: Session = Depends(get_db), user: User = Depends(lecturer_or_admin)):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam.lecturer_id != user.id and user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Not your exam")
    db.delete(exam)
    db.commit()