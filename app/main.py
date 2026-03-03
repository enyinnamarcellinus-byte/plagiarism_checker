from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .auth import create_token, hash_password, verify_password
from .database import Base, engine, get_db
from .models import User
from .routers import admin, auth, courses, dashboard, exams, reports, student, submissions
from .schemas import TokenOut, UserCreate, UserOut

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Plagiarism Detection System")

for router in [
    auth.router,
    courses.router,
    exams.router,
    submissions.router,
    reports.router,
    dashboard.router,
    student.router,
    admin.router,
]:
    app.include_router(router)


@app.get("/")
def root():
    return RedirectResponse(url="/login")


# JSON API auth (Swagger / API clients)
@app.post("/auth/token", response_model=TokenOut)
def login_api(
    db: Annotated[Session, Depends(get_db)], form: Annotated[OAuth2PasswordRequestForm, Depends()]
):
    user = db.query(User).filter_by(email=form.username).first()
    if not user or not verify_password(form.password, user.hashed_pw):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad credentials")
    return {"access_token": create_token(user.id, user.role), "token_type": "bearer"}


@app.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_api(body: UserCreate, db: Annotated[Session, Depends(get_db)]):
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=body.email, name=body.name, role=body.role, hashed_pw=hash_password(body.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
