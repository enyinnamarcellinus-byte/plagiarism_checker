from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread":False} if "sqlite" in
settings.database_url else {}
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoFlush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()