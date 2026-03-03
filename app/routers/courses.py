from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import lecturer_or_admin
from ..database import get_db
from ..models import AuditAction, Course, Role, User
from ..schemas import CourseCreate, CourseOut
from ..services.audit import log as audit

router = APIRouter(prefix="/courses", tags=["courses"])


@router.post("/", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
def create_course(
    body: CourseCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
):
    course = Course(**body.model_dump(), lecturer_id=user.id)
    db.add(course)
    db.commit()
    db.refresh(course)
    audit(
        db, AuditAction.course_created, user_id=user.id, target_id=course.id, target_type="course"
    )
    return course


@router.get("/", response_model=list[CourseOut])
def list_courses(
    db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(lecturer_or_admin)]
):
    q = db.query(Course)
    if user.role == Role.lecturer:
        q = q.filter_by(lecturer_id=user.id)
    return q.all()


@router.get("/{course_id}", response_model=CourseOut)
def get_course(
    course_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if user.role == Role.lecturer and course.lecturer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your course")
    return course


@router.put("/{course_id}", response_model=CourseOut)
def update_course(
    course_id: int,
    body: CourseCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if user.role == Role.lecturer and course.lecturer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your course")
    for k, v in body.model_dump().items():
        setattr(course, k, v)
    db.commit()
    db.refresh(course)
    return course


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if user.role == Role.lecturer and course.lecturer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your course")
    db.delete(course)
    db.commit()
