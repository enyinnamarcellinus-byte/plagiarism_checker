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


# ── HTML Dashboard ────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    courses = db.query(Course).order_by(Course.created_at.desc()).all()
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(50).all()
    lecturers = [u for u in users if u.role in (Role.lecturer, Role.admin)]
    students = [u for u in users if u.role == Role.student]
    departments = db.query(Department).order_by(Department.name).all()
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "user": user,
            "users": users,
            "courses": courses,
            "lecturers": lecturers,
            "students": students,
            "departments": departments,
            "logs": logs,
        },
    )


@router.post("/courses/new", response_class=HTMLResponse)
async def create_course(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
    title: str = Form(...),
    code: str = Form(...),
    description: str = Form(""),
    lecturer_id: int = Form(...),
    department_ids: list[int] = Form(default=[]),
):
    lecturer = db.get(User, lecturer_id)
    if not lecturer or lecturer.role not in (Role.lecturer, Role.admin):
        raise HTTPException(status_code=400, detail="Selected user is not a lecturer")
    course = Course(
        title=title, code=code, description=description or None, lecturer_id=lecturer_id
    )
    db.add(course)
    db.flush()
    for department_id in department_ids:
        if db.get(Department, department_id):
            db.add(CourseDepartment(course_id=course.id, department_id=department_id))
    db.commit()
    audit(
        db, AuditAction.course_created, user_id=user.id, target_id=course.id, target_type="course"
    )
    return RedirectResponse(url="/admin/", status_code=303)


@router.post("/courses/{course_id}/lecturer", response_class=HTMLResponse)
async def assign_course_lecturer(
    course_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
    lecturer_id: int = Form(...),
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    lecturer = db.get(User, lecturer_id)
    if not lecturer or lecturer.role not in (Role.lecturer, Role.admin):
        raise HTTPException(status_code=400, detail="Selected user is not a lecturer")
    course.lecturer_id = lecturer.id
    db.commit()
    return RedirectResponse(url="/admin/", status_code=303)


@router.post("/courses/{course_id}/delete", response_class=HTMLResponse)
async def delete_course_form(
    course_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    db.delete(course)
    db.commit()
    return RedirectResponse(url="/admin/", status_code=303)


@router.post("/enrollments/new", response_class=HTMLResponse)
async def enroll_student_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
    student_id: int = Form(...),
    course_id: int = Form(...),
):
    student = db.get(User, student_id)
    course = db.get(Course, course_id)
    if not student or student.role != Role.student:
        raise HTTPException(status_code=400, detail="User is not a student")
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    enrollment = Enrollment(student_id=student_id, course_id=course_id)
    db.add(enrollment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # already enrolled — silently ignore in UI
    audit(
        db,
        AuditAction.enrollment_created,
        user_id=user.id,
        target_id=course_id,
        target_type="course",
    )
    return RedirectResponse(url="/admin/", status_code=303)


@router.post("/enrollments/{enrollment_id}/delete", response_class=HTMLResponse)
async def unenroll_student_form(
    enrollment_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(admin_only)],
):
    e = db.get(Enrollment, enrollment_id)
    if e:
        db.delete(e)
        db.commit()
    return RedirectResponse(url="/admin/", status_code=303)


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
    return RedirectResponse(url="/admin/", status_code=303)


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
    return RedirectResponse(url="/admin/", status_code=303)


# ── HTMX helpers ─────────────────────────────────────────────────────────────


def _user_row_html(target: User, admin: User) -> HTMLResponse:
    role_colors = {
        "student": "bg-slate-100 text-slate-600",
        "lecturer": "bg-blue-100 text-blue-700",
        "admin": "bg-purple-100 text-purple-700",
    }
    rc = role_colors.get(target.role, "bg-slate-100 text-slate-600")
    active_badge = (
        '<span class="px-2 py-0.5 rounded-full text-xs font-bold bg-green-100 text-green-700">Active</span>'
        if target.is_active
        else '<span class="px-2 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-600">Inactive</span>'
    )
    if target.id != admin.id:
        role_select = (
            f'<select hx-patch="/admin/users/{target.id}/role" hx-include="this" '
            f'hx-target="#user-row-{target.id}" hx-swap="outerHTML" name="role" '
            f'class="text-xs font-bold px-2 py-1 rounded-full border-0 cursor-pointer focus:outline-none {rc}">'
            f'<option value="student" {"selected" if target.role == "student" else ""}>student</option>'
            f'<option value="lecturer" {"selected" if target.role == "lecturer" else ""}>lecturer</option>'
            f'<option value="admin" {"selected" if target.role == "admin" else ""}>admin</option>'
            f"</select>"
        )
        action = (
            f'<button hx-patch="/admin/users/{target.id}/deactivate" hx-confirm="Deactivate {target.name}?" '
            f'hx-target="#user-row-{target.id}" hx-swap="outerHTML" '
            f'class="text-xs text-red-500 hover:underline font-semibold">Deactivate</button>'
            if target.is_active
            else f'<button hx-patch="/admin/users/{target.id}/activate" hx-target="#user-row-{target.id}" '
            f'hx-swap="outerHTML" class="text-xs text-green-600 hover:underline font-semibold">Activate</button>'
        )
    else:
        role_select = (
            f'<span class="px-2 py-0.5 rounded-full text-xs font-bold {rc}">{target.role}</span>'
        )
        action = ""

    return HTMLResponse(
        f'<tr class="hover:bg-slate-50 transition-colors" id="user-row-{target.id}">'
        f'<td class="px-4 py-3"><p class="font-semibold text-slate-800">{target.name}</p>'
        f'<p class="text-xs text-slate-400">{target.email}</p></td>'
        f'<td class="px-4 py-3">{role_select}</td>'
        f'<td class="px-4 py-3">{active_badge}</td>'
        f'<td class="px-4 py-3 text-right">{action}</td>'
        f"</tr>"
    )
