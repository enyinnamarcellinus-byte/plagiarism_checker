import enum
from datetime import datetime, UTC
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text
)
from sqlalchemy.orm import relationship
from .database import Base

def utcnow():
    return datetime.now(UTC)

# --- Enums ---

class Role(str, enum.Enum):
    student = "student"
    lecturer = "lecturer"
    admin = "admin"

class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"

class ReviewStatus(str, enum.Enum):
    pending = "pending"
    suspected = "suspected"
    cleared = "cleared"
    reviewed = "reviewed"

class PlagiarismType(str, enum.Enum):
    verbatim = "verbatim"
    near_copy = "near_copy"
    patchwork = "patchwork"
    structural = "structural"

# --- Models ---

class User(Base):
    __tablename__ = "users"
    id          = Column(Integer, primary_key=True)
    email       = Column(String, unique=True, nullable=False, index=True)
    name        = Column(String, nullable=False)
    hashed_pw   = Column(String, nullable=False)
    role        = Column(Enum(Role), nullable=False, default=Role.student)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), default=utcnow)

    exams       = relationship("Exam", back_populates="lecturer")
    submissions = relationship("Submission", back_populates="student")


class Exam(Base):
    __tablename__ = "exams"
    id              = Column(Integer, primary_key=True)
    lecturer_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    title           = Column(String, nullable=False)
    course          = Column(String, nullable=False)
    description     = Column(Text)
    opens_at        = Column(DateTime(timezone=True), nullable=False)
    closes_at       = Column(DateTime(timezone=True), nullable=False)
    allowed_formats = Column(String, default="pdf,docx,txt")  # comma-separated
    max_file_mb     = Column(Integer, default=10)
    created_at      = Column(DateTime(timezone=True), default=utcnow)

    lecturer    = relationship("User", back_populates="exams")
    submissions = relationship("Submission", back_populates="exam")
    job         = relationship("PlagiarismJob", back_populates="exam", uselist=False)


class Submission(Base):
    __tablename__ = "submissions"
    id              = Column(Integer, primary_key=True)
    exam_id         = Column(Integer, ForeignKey("exams.id"), nullable=False)
    student_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    file_path       = Column(String, nullable=False)   # path to stored original
    extracted_text  = Column(Text)                     # populated after extraction
    uploaded_at     = Column(DateTime(timezone=True), default=utcnow)

    exam    = relationship("Exam", back_populates="submissions")
    student = relationship("User", back_populates="submissions")
    # pairs where this submission is either doc_a or doc_b
    pairs_as_a = relationship("SimilarityPair", foreign_keys="SimilarityPair.submission_a_id", back_populates="submission_a")
    pairs_as_b = relationship("SimilarityPair", foreign_keys="SimilarityPair.submission_b_id", back_populates="submission_b")


class PlagiarismJob(Base):
    """One job per exam. Tracks the async analysis pipeline."""
    __tablename__ = "plagiarism_jobs"
    id          = Column(Integer, primary_key=True)
    exam_id     = Column(Integer, ForeignKey("exams.id"), unique=True, nullable=False)
    celery_id   = Column(String)                          # Celery task UUID
    status      = Column(Enum(JobStatus), default=JobStatus.pending)
    error       = Column(Text)
    queued_at   = Column(DateTime(timezone=True), default=utcnow)
    finished_at = Column(DateTime(timezone=True))

    exam  = relationship("Exam", back_populates="job")


class SimilarityPair(Base):
    """Comparison result between two submissions in the same exam."""
    __tablename__ = "similarity_pairs"
    id               = Column(Integer, primary_key=True)
    submission_a_id  = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    submission_b_id  = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    similarity_score = Column(Float, nullable=False)   # 0.0 – 1.0
    created_at       = Column(DateTime(timezone=True), default=utcnow)

    submission_a  = relationship("Submission", foreign_keys=[submission_a_id], back_populates="pairs_as_a")
    submission_b  = relationship("Submission", foreign_keys=[submission_b_id], back_populates="pairs_as_b")
    fragments     = relationship("MatchedFragment", back_populates="pair", cascade="all, delete-orphan")
    type_result   = relationship("PlagiarismTypeResult", back_populates="pair", uselist=False, cascade="all, delete-orphan")
    review        = relationship("ReviewDecision", back_populates="pair", uselist=False, cascade="all, delete-orphan")


class MatchedFragment(Base):
    """A specific text span that matched between two submissions."""
    __tablename__ = "matched_fragments"
    id          = Column(Integer, primary_key=True)
    pair_id     = Column(Integer, ForeignKey("similarity_pairs.id"), nullable=False)
    text        = Column(Text, nullable=False)
    # token positions within each submission's extracted text
    start_a     = Column(Integer)
    end_a       = Column(Integer)
    start_b     = Column(Integer)
    end_b       = Column(Integer)
    length      = Column(Integer)   # token length of fragment

    pair = relationship("SimilarityPair", back_populates="fragments")


class PlagiarismTypeResult(Base):
    """Classification of the dominant plagiarism pattern for a pair."""
    __tablename__ = "plagiarism_type_results"
    id               = Column(Integer, primary_key=True)
    pair_id          = Column(Integer, ForeignKey("similarity_pairs.id"), unique=True, nullable=False)
    predicted_type   = Column(Enum(PlagiarismType), nullable=False)
    # confidence scores for each type (0.0 – 1.0), all four stored
    score_verbatim   = Column(Float, default=0.0)
    score_near_copy  = Column(Float, default=0.0)
    score_patchwork  = Column(Float, default=0.0)
    score_structural = Column(Float, default=0.0)

    pair = relationship("SimilarityPair", back_populates="type_result")


class ReviewDecision(Base):
    """Lecturer's verdict on a flagged pair."""
    __tablename__ = "review_decisions"
    id          = Column(Integer, primary_key=True)
    pair_id     = Column(Integer, ForeignKey("similarity_pairs.id"), unique=True, nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status      = Column(Enum(ReviewStatus), default=ReviewStatus.pending)
    notes       = Column(Text)
    decided_at  = Column(DateTime(timezone=True), default=utcnow)

    pair     = relationship("SimilarityPair", back_populates="review")
    reviewer = relationship("User")