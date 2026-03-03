from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import create_token, hash_password, verify_password
from ..database import get_db
from ..models import AuditAction, Role, User
from ..services.audit import log as audit

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request, "error": None})


@router.post("/login")
async def login_submit(
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    ip = request.client.host if request.client else None
    user = db.query(User).filter_by(email=email).first()

    if not user or not verify_password(password, user.hashed_pw):
        audit(db, AuditAction.login, detail={"email": email, "success": False}, ip_address=ip)
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Invalid email or password"},
            status_code=400,
        )

    audit(db, AuditAction.login, user_id=user.id, detail={"success": True}, ip_address=ip)
    token = create_token(user.id, user.role)
    redirect = "/student/dashboard" if user.role == Role.student else "/dashboard/"
    response = RedirectResponse(url=redirect, status_code=302)
    response.set_cookie(
        key="session", value=token, httponly=True, samesite="lax", max_age=_max_age()
    )
    return response


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("auth/register.html", {"request": request, "error": None})


@router.post("/register")
async def register_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    if db.query(User).filter_by(email=email).first():
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Email already registered"},
            status_code=400,
        )
    user_role = Role(role) if role in Role._value2member_map_ else Role.student
    user = User(email=email, name=name, role=user_role, hashed_pw=hash_password(password))
    db.add(user)
    db.commit()
    audit(db, AuditAction.user_created, user_id=user.id, target_id=user.id, target_type="user")
    return RedirectResponse(url="/login", status_code=302)


@router.get("/logout")
def logout(request: Request, db: Annotated[Session, Depends(get_db)]):
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session")
    return response


def _max_age() -> int:
    from ..config import settings

    return settings.access_token_expire_minutes * 60
