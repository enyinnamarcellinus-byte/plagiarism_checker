from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .auth import create_token, hash_password, verify_password
from .database import Base, engine, get_db
from .models import User
from .schemas import TokenOut, UserCreate, UserOut
from .routers import exams, submissions

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Plagiarism Detection System")
app.include_router(exams.router)
app.include_router(submissions.router)


@app.post("/auth/token", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=form.username).first()
    if not user or not verify_password(form.password, user.hashed_pw):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad credentials")
    return {"access_token": create_token(user.id, user.role), "token_type": "bearer"}


@app.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=body.email, name=body.name, role=body.role, hashed_pw=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user