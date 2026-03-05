import io
import pytest
from datetime import datetime, timedelta, timezone, UTC
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.auth import hash_password, create_token
from app.models import Course, CourseDepartment, Department, Exam, Role, Submission, User

_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
_Session = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="session", autouse=True)
def _tables():
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)

@pytest.fixture(scope="session", autouse=True)
def _patch_settings():
    settings.fernet_key = Fernet.generate_key().decode()


@pytest.fixture
def db():
    conn = _engine.connect()
    tx = conn.begin()
    session = _Session(bind=conn)
    yield session
    session.close()
    tx.rollback()
    conn.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _now():
    return datetime.now(UTC)


def make_user(db, email, name, role, active=True, department_id=None) -> User:
    u = User(email=email, name=name, role=role, department_id=department_id,
             hashed_pw=hash_password("password123"), is_active=active)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# Keep _user as alias so test_api.py inline calls still work
_user = make_user


@pytest.fixture
def student(db, department):
    return make_user(db, "student@test.com", "Alice", Role.student, department_id=department.id)

@pytest.fixture
def lecturer(db):
    return make_user(db, "lecturer@test.com", "Bob", Role.lecturer)


@pytest.fixture
def other_lecturer(db):
    return make_user(db, "other@test.com", "Carol", Role.lecturer)

@pytest.fixture
def admin(db):
    return make_user(db, "admin@test.com", "Dave", Role.admin)

@pytest.fixture
def inactive(db):
    return make_user(db, "inactive@test.com", "Eve", Role.student, active=False)


def auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user.id, user.role)}"}


@pytest.fixture
def department(db) -> Department:
    d = Department(name="Computer Science", code="CSC")
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


@pytest.fixture
def course(db, lecturer, department) -> Course:
    c = Course(title="Computer Science 101", code="CS101", lecturer_id=lecturer.id)
    db.add(c)
    db.flush()
    db.add(CourseDepartment(course_id=c.id, department_id=department.id))
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture
def open_exam(db, course) -> Exam:
    e = Exam(
        course_id=course.id, title="Midterm Essay",
        opens_at=_now() - timedelta(hours=1),
        closes_at=_now() + timedelta(hours=24),
        allowed_formats="pdf,docx,txt", max_file_mb=10,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


@pytest.fixture
def closed_exam(db, course) -> Exam:
    e = Exam(
        course_id=course.id, title="Past Exam",
        opens_at=_now() - timedelta(days=7),
        closes_at=_now() - timedelta(days=1),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


@pytest.fixture
def future_exam(db, course) -> Exam:
    e = Exam(
        course_id=course.id, title="Future Exam",
        opens_at=_now() + timedelta(days=1),
        closes_at=_now() + timedelta(days=7),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


@pytest.fixture
def submission(db, open_exam, student) -> Submission:
    s = Submission(
        exam_id=open_exam.id, student_id=student.id,
        file_path="uploads/1/test.txt",
        extracted_text="the mitochondria is the powerhouse of the cell " * 30,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def txt_upload(content: str = "sample essay " * 40):
    return ("file", ("essay.txt", io.BytesIO(content.encode()), "text/plain"))


def oversized_upload(mb: int = 15):
    return ("file", ("big.txt", io.BytesIO(b"x" * mb * 1024 * 1024), "text/plain"))