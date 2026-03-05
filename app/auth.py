from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Role, User

pwd_ctx = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def create_token(user_id: int, role: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "role": role, "exp": expire}, settings.secret_key, settings.algorithm
    )


def _decode_token(token: str, db: Session) -> User:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )
    return user


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    bearer: Annotated[str | None, Depends(oauth2_scheme)] = None,
    session: Annotated[str | None, Cookie(alias="session")] = None,
) -> User:
    token = bearer or session
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _decode_token(token, db)


def get_current_user_optional(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    bearer: Annotated[str | None, Depends(oauth2_scheme)] = None,
    session: Annotated[str | None, Cookie(alias="session")] = None,
) -> User | None:
    token = bearer or session
    if not token:
        return None
    try:
        return _decode_token(token, db)
    except HTTPException:
        return None


def require_role(*roles: Role):
    def guard(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return user

    return guard


lecturer_or_admin = require_role(Role.lecturer, Role.admin)
student_only = require_role(Role.student)
admin_only = require_role(Role.admin)
