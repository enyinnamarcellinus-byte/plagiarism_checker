from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, lecturer_or_admin
from ..database import get_db
from ..models import AuditAction, Course, Exam, Role, User
from ..schemas import ExamCreate, ExamOut
from ..services.audit import log as audit

router = APIRouter(prefix="/exams", tags=["exams"])


def _assert_course_access(course_id: int, user: User, db: Session) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if user.role == Role.lecturer and course.lecturer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your course")
    return course


@router.post("/", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
def create_exam(body: ExamCreate, db: Session = Depends(get_db), user: User = Depends(lecturer_or_admin)):
    _assert_course_access(body.course_id, user, db)
    exam = Exam(**body.model_dump())
    db.add(exam)
    db.commit()
    db.refresh(exam)
    audit(db, AuditAction.exam_created, user_id=user.id, target_id=exam.id, target_type="exam")
    return exam


@router.get("/", response_model=list[ExamOut])
def list_exams(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role in (Role.lecturer, Role.admin):
        course_ids = [c.id for c in db.query(Course).filter_by(lecturer_id=user.id).all()]
        return db.query(Exam).filter(Exam.course_id.in_(course_ids)).all()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return db.query(Exam).filter(Exam.opens_at <= now, Exam.closes_at >= now).all()


@router.get("/{exam_id}", response_model=ExamOut)
def get_exam(exam_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if user.role == Role.lecturer and exam.course.lecturer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your exam")
    return exam


@router.put("/{exam_id}", response_model=ExamOut)
def update_exam(exam_id: int, body: ExamCreate, db: Session = Depends(get_db), user: User = Depends(lecturer_or_admin)):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    _assert_course_access(body.course_id, user, db)
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
    if user.role == Role.lecturer and exam.course.lecturer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your exam")
    db.delete(exam)
    db.commit()
