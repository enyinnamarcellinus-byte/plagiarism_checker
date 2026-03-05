from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import admin_only
from ..database import get_db
from ..models import (
    AuditAction,
    AuditLog,
    Course,
    CourseDepartment,
    Department,
    Enrollment,
    Role,
    User,
)
from ..schemas import DepartmentOut, UserOut
from ..services.audit import log as audit

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")


# ── JSON API ─────────────────────────────────────────────────────────────────


@router.get("/users", response_model=list[UserOut])
def list_users(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(admin_only)]):
    return db.query(User).order_by(User.created_at.desc()).all()


@router.patch("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404)
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    target.is_active = False
    db.commit()
    audit(
        db, AuditAction.user_deactivated, user_id=admin.id, target_id=target.id, target_type="user"
    )
    db.refresh(target)
    return target


@router.patch("/users/{user_id}/activate")
def activate_user(
    user_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404)
    target.is_active = True
    db.commit()
    db.refresh(target)
    return target


@router.patch("/users/{user_id}/role")
def change_role(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
    role: str
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404)
    try:
        target.role = Role(role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {role}")
    db.commit()
    db.refresh(target)
    return target


@router.get("/audit-logs", response_model=list)
def get_audit_logs(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
    limit: int = 100,
):
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    return db.query(Department).order_by(Department.name).all()


@router.post("/departments")
def create_department_api(
    name: str,
    code: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    dept = Department(name=name.strip(), code=code.strip().upper())
    db.add(dept)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        dept = db.query(Department).filter_by(code=code.strip().upper()).first()
        if not dept:
            raise HTTPException(status_code=409, detail="Department already exists")
    db.refresh(dept)
    return dept


# ── Enrollment JSON API ───────────────────────────────────────────────────────


@router.post("/enrollments")
def enroll_student(
    student_id: int,
    course_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    student = db.get(User, student_id)
    if not student or student.role != Role.student:
        raise HTTPException(status_code=400, detail="User is not a student")
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found")
    enrollment = Enrollment(student_id=student_id, course_id=course_id)
    db.add(enrollment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Already enrolled")
    audit(
        db,
        AuditAction.enrollment_created,
        user_id=admin.id,
        target_id=course_id,
        target_type="course",
    )
    db.refresh(enrollment)
    return enrollment


@router.delete("/enrollments/{enrollment_id}", status_code=204)
def unenroll_student(
    enrollment_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    e = db.get(Enrollment, enrollment_id)
    if not e:
        raise HTTPException(status_code=404)
    db.delete(e)
    db.commit()



# ── HTML Pages ────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def admin_index(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    total_users = db.query(User).count()
    total_courses = db.query(Course).count()
    total_departments = db.query(Department).count()
    total_submissions = db.query(Enrollment).count()
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(20).all()
    return templates.TemplateResponse("admin/index.html", {
        "request": request, "user": user,
        "total_users": total_users, "total_courses": total_courses,
        "total_departments": total_departments, "total_submissions": total_submissions,
        "logs": logs,
    })


@router.get("/users-list", response_class=HTMLResponse)
def admin_users(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    departments = db.query(Department).order_by(Department.name).all()
    return templates.TemplateResponse("admin/users.html", {
        "request": request, "user": user,
        "users": users, "departments": departments,
    })


@router.get("/departments-list", response_class=HTMLResponse)
def admin_departments(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    departments = db.query(Department).order_by(Department.name).all()
    return templates.TemplateResponse("admin/departments.html", {
        "request": request, "user": user, "departments": departments,
    })


@router.get("/departments-list/{dept_id}", response_class=HTMLResponse)
def admin_department_detail(
    dept_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    dept = db.get(Department, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    course_ids = [l.course_id for l in db.query(CourseDepartment).filter_by(department_id=dept_id).all()]
    courses = db.query(Course).filter(Course.id.in_(course_ids)).order_by(Course.code).all()
    lecturers = db.query(User).filter(User.role.in_([Role.lecturer, Role.admin])).order_by(User.name).all()
    return templates.TemplateResponse("admin/department.html", {
        "request": request, "user": user,
        "dept": dept, "courses": courses, "lecturers": lecturers,
    })


@router.get("/courses-list/{course_id}", response_class=HTMLResponse)
def admin_course_detail(
    course_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    lecturers = db.query(User).filter(User.role.in_([Role.lecturer, Role.admin])).order_by(User.name).all()
    students = db.query(User).filter_by(role=Role.student).order_by(User.name).all()
    enrolled_ids = {e.student_id for e in course.enrollments}
    return templates.TemplateResponse("admin/course.html", {
        "request": request, "user": user,
        "course": course, "lecturers": lecturers,
        "students": students, "enrolled_ids": enrolled_ids,
    })


# ── HTML Form POSTs ───────────────────────────────────────────────────────────


@router.post("/departments/new", response_class=HTMLResponse)
async def create_department(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
    name: str = Form(...),
    code: str = Form(...),
):
    dept = Department(name=name.strip(), code=code.strip().upper())
    db.add(dept)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse(url="/admin/departments-list", status_code=303)


@router.post("/courses/new", response_class=HTMLResponse)
async def create_course(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
    title: str = Form(...),
    code: str = Form(...),
    description: str = Form(""),
    lecturer_id: int = Form(...),
    dept_id: int = Form(...),
    department_ids: list[int] = Form(default=[]),
):
    lecturer = db.get(User, lecturer_id)
    if not lecturer or lecturer.role not in (Role.lecturer, Role.admin):
        raise HTTPException(status_code=400, detail="Selected user is not a lecturer")
    course = Course(title=title, code=code, description=description or None, lecturer_id=lecturer_id)
    db.add(course)
    db.flush()
    for department_id in department_ids:
        if db.get(Department, department_id):
            db.add(CourseDepartment(course_id=course.id, department_id=department_id))
    db.commit()
    audit(db, AuditAction.course_created, user_id=user.id, target_id=course.id, target_type="course")
    return RedirectResponse(url=f"/admin/departments-list/{dept_id}", status_code=303)


@router.post("/courses/{course_id}/lecturer", response_class=HTMLResponse)
async def assign_course_lecturer(
    course_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
    lecturer_id: int = Form(...),
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404)
    lecturer = db.get(User, lecturer_id)
    if not lecturer or lecturer.role not in (Role.lecturer, Role.admin):
        raise HTTPException(status_code=400, detail="Selected user is not a lecturer")
    course.lecturer_id = lecturer.id
    db.commit()
    return RedirectResponse(url=f"/admin/courses-list/{course_id}", status_code=303)


@router.post("/courses/{course_id}/delete", response_class=HTMLResponse)
async def delete_course_form(
    course_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404)
    # find first linked department for redirect
    link = db.query(CourseDepartment).filter_by(course_id=course_id).first()
    dept_id = link.department_id if link else None
    db.delete(course)
    db.commit()
    redirect = f"/admin/departments-list/{dept_id}" if dept_id else "/admin/departments-list"
    return RedirectResponse(url=redirect, status_code=303)


@router.post("/enrollments/new", response_class=HTMLResponse)
async def enroll_student_form(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
    student_id: int = Form(...),
    course_id: int = Form(...),
):
    student = db.get(User, student_id)
    course = db.get(Course, course_id)
    if not student or student.role != Role.student:
        raise HTTPException(status_code=400)
    if not course:
        raise HTTPException(status_code=404)
    enrollment = Enrollment(student_id=student_id, course_id=course_id)
    db.add(enrollment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    audit(db, AuditAction.enrollment_created, user_id=user.id, target_id=course_id, target_type="course")
    return RedirectResponse(url=f"/admin/courses-list/{course_id}", status_code=303)


@router.post("/enrollments/{enrollment_id}/delete", response_class=HTMLResponse)
async def unenroll_student_form(
    enrollment_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    e = db.get(Enrollment, enrollment_id)
    if not e:
        raise HTTPException(status_code=404)
    course_id = e.course_id
    db.delete(e)
    db.commit()
    return RedirectResponse(url=f"/admin/courses-list/{course_id}", status_code=303)


@router.post("/users/{user_id}/department", response_class=HTMLResponse)
async def assign_user_department(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
    department_id: int = Form(...),
):
    target = db.get(User, user_id)
    department = db.get(Department, department_id)
    if not target or not department:
        raise HTTPException(status_code=404)
    target.department_id = department.id
    db.commit()
    return RedirectResponse(url="/admin/users-list", status_code=303)