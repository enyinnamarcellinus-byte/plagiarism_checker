import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text
)
from sqlalchemy.orm import relationship
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

# --- Enums ---

class Role(str, enum.Enum):
    student  = "student"
    lecturer = "lecturer"
    admin    = "admin"

class JobStatus(str, enum.Enum):
    pending   = "pending"
    running   = "running"
    completed = "completed"
    failed    = "failed"

class ReviewStatus(str, enum.Enum):
    pending   = "pending"
    suspected = "suspected"
    cleared   = "cleared"
    reviewed  = "reviewed"

class PlagiarismType(str, enum.Enum):
    verbatim   = "verbatim"
    near_copy  = "near_copy"
    patchwork  = "patchwork"
    structural = "structural"

class AuditAction(str, enum.Enum):
    login            = "login"
    logout           = "logout"
    submission_upload = "submission_upload"
    report_viewed    = "report_viewed"
    review_decision  = "review_decision"
    report_exported  = "report_exported"
    user_created     = "user_created"
    user_deactivated = "user_deactivated"
    exam_created     = "exam_created"
    course_created   = "course_created"

# --- Models ---

class User(Base):
    __tablename__ = "users"
    id         = Column(Integer, primary_key=True)
    email      = Column(String, unique=True, nullable=False, index=True)
    name       = Column(String, nullable=False)
    hashed_pw  = Column(String, nullable=False)
    role       = Column(Enum(Role), nullable=False, default=Role.student)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    courses     = relationship("Course", back_populates="lecturer")
    submissions = relationship("Submission", back_populates="student")
    audit_logs  = relationship("AuditLog", back_populates="user")


class Course(Base):
    __tablename__ = "courses"
    id          = Column(Integer, primary_key=True)
    lecturer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title       = Column(String, nullable=False)
    code        = Column(String, nullable=False)   # e.g. "CS301"
    description = Column(Text)
    created_at  = Column(DateTime(timezone=True), default=utcnow)

    lecturer = relationship("User", back_populates="courses")
    exams    = relationship("Exam", back_populates="course")


class Exam(Base):
    __tablename__ = "exams"
    id                  = Column(Integer, primary_key=True)
    course_id           = Column(Integer, ForeignKey("courses.id"), nullable=False)
    title               = Column(String, nullable=False)
    description         = Column(Text)
    opens_at            = Column(DateTime(timezone=True), nullable=False)
    closes_at           = Column(DateTime(timezone=True), nullable=False)
    allowed_formats     = Column(String, default="pdf,docx,txt")
    max_file_mb         = Column(Integer, default=10)
    # Lecturer sets this: pairs above threshold are flagged. Default 40%.
    similarity_threshold = Column(Float, default=0.4)
    created_at          = Column(DateTime(timezone=True), default=utcnow)

    course      = relationship("Course", back_populates="exams")
    submissions = relationship("Submission", back_populates="exam")
    job         = relationship("PlagiarismJob", back_populates="exam", uselist=False)

    @property
    def lecturer_id(self):
        return self.course.lecturer_id if self.course else None


class Submission(Base):
    __tablename__ = "submissions"
    id               = Column(Integer, primary_key=True)
    exam_id          = Column(Integer, ForeignKey("exams.id"), nullable=False)
    student_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    file_path        = Column(String, nullable=False)
    extracted_text   = Column(Text)
    originality_score = Column(Float)   # 0.0–1.0, populated after analysis. 1.0 = fully original
    uploaded_at      = Column(DateTime(timezone=True), default=utcnow)

    exam       = relationship("Exam", back_populates="submissions")
    student    = relationship("User", back_populates="submissions")
    pairs_as_a = relationship("SimilarityPair", foreign_keys="SimilarityPair.submission_a_id", back_populates="submission_a")
    pairs_as_b = relationship("SimilarityPair", foreign_keys="SimilarityPair.submission_b_id", back_populates="submission_b")


class PlagiarismJob(Base):
    __tablename__ = "plagiarism_jobs"
    id          = Column(Integer, primary_key=True)
    exam_id     = Column(Integer, ForeignKey("exams.id"), unique=True, nullable=False)
    celery_id   = Column(String)
    status      = Column(Enum(JobStatus), default=JobStatus.pending)
    error       = Column(Text)
    queued_at   = Column(DateTime(timezone=True), default=utcnow)
    finished_at = Column(DateTime(timezone=True))

    exam = relationship("Exam", back_populates="job")


class SimilarityPair(Base):
    __tablename__ = "similarity_pairs"
    id               = Column(Integer, primary_key=True)
    submission_a_id  = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    submission_b_id  = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    similarity_score = Column(Float, nullable=False)   # cosine TF-IDF
    jaccard_score    = Column(Float)                   # Jaccard on shingle sets
    originality_score = Column(Float)                  # 1 - max(similarity, jaccard)
    created_at       = Column(DateTime(timezone=True), default=utcnow)

    submission_a = relationship("Submission", foreign_keys=[submission_a_id], back_populates="pairs_as_a")
    submission_b = relationship("Submission", foreign_keys=[submission_b_id], back_populates="pairs_as_b")
    fragments    = relationship("MatchedFragment", back_populates="pair", cascade="all, delete-orphan")
    type_result  = relationship("PlagiarismTypeResult", back_populates="pair", uselist=False, cascade="all, delete-orphan")
    review       = relationship("ReviewDecision", back_populates="pair", uselist=False, cascade="all, delete-orphan")


class MatchedFragment(Base):
    __tablename__ = "matched_fragments"
    id      = Column(Integer, primary_key=True)
    pair_id = Column(Integer, ForeignKey("similarity_pairs.id"), nullable=False)
    text    = Column(Text, nullable=False)
    start_a = Column(Integer)
    end_a   = Column(Integer)
    start_b = Column(Integer)
    end_b   = Column(Integer)
    length  = Column(Integer)

    pair = relationship("SimilarityPair", back_populates="fragments")


class PlagiarismTypeResult(Base):
    __tablename__ = "plagiarism_type_results"
    id               = Column(Integer, primary_key=True)
    pair_id          = Column(Integer, ForeignKey("similarity_pairs.id"), unique=True, nullable=False)
    predicted_type   = Column(Enum(PlagiarismType), nullable=False)
    score_verbatim   = Column(Float, default=0.0)
    score_near_copy  = Column(Float, default=0.0)
    score_patchwork  = Column(Float, default=0.0)
    score_structural = Column(Float, default=0.0)

    pair = relationship("SimilarityPair", back_populates="type_result")


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    id          = Column(Integer, primary_key=True)
    pair_id     = Column(Integer, ForeignKey("similarity_pairs.id"), unique=True, nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status      = Column(Enum(ReviewStatus), default=ReviewStatus.pending)
    notes       = Column(Text)
    decided_at  = Column(DateTime(timezone=True), default=utcnow)

    pair     = relationship("SimilarityPair", back_populates="review")
    reviewer = relationship("User")


class AuditLog(Base):
    """Append-only. Never delete rows from this table."""
    __tablename__ = "audit_logs"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)  # nullable for failed logins
    action     = Column(Enum(AuditAction), nullable=False)
    target_id  = Column(Integer)    # e.g. submission_id, exam_id, pair_id
    target_type = Column(String)    # e.g. "submission", "exam", "pair"
    detail     = Column(Text)       # free-form JSON string for extra context
    ip_address = Column(String)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="audit_logs")