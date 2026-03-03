from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator
from .models import AuditAction, JobStatus, PlagiarismType, ReviewStatus, Role


# --- Auth ---

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: Role = Role.student

class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: Role
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


# --- Course ---

class CourseCreate(BaseModel):
    title: str
    code: str
    description: str | None = None

class CourseOut(BaseModel):
    id: int
    title: str
    code: str
    description: str | None
    lecturer_id: int
    created_at: datetime
    model_config = {"from_attributes": True}


# --- Exam ---

class ExamCreate(BaseModel):
    course_id: int
    title: str
    description: str | None = None
    opens_at: datetime
    closes_at: datetime
    allowed_formats: str = "pdf,docx,txt"
    max_file_mb: int = 10
    similarity_threshold: float = 0.4

    @field_validator("closes_at")
    @classmethod
    def closes_after_opens(cls, v, info):
        if "opens_at" in info.data and v <= info.data["opens_at"]:
            raise ValueError("closes_at must be after opens_at")
        return v

class ExamOut(BaseModel):
    id: int
    course_id: int
    title: str
    description: str | None
    opens_at: datetime
    closes_at: datetime
    allowed_formats: str
    max_file_mb: int
    similarity_threshold: float
    model_config = {"from_attributes": True}


# --- Submission ---

class SubmissionOut(BaseModel):
    id: int
    exam_id: int
    student_id: int
    uploaded_at: datetime
    originality_score: float | None
    model_config = {"from_attributes": True}


# --- Job ---

class JobOut(BaseModel):
    id: int
    exam_id: int
    status: JobStatus
    queued_at: datetime
    finished_at: datetime | None
    error: str | None
    model_config = {"from_attributes": True}


# --- Similarity / Reports ---

class FragmentOut(BaseModel):
    id: int
    text: str
    start_a: int
    end_a: int
    start_b: int
    end_b: int
    length: int
    model_config = {"from_attributes": True}

class TypeResultOut(BaseModel):
    predicted_type: PlagiarismType
    score_verbatim: float
    score_near_copy: float
    score_patchwork: float
    score_structural: float
    model_config = {"from_attributes": True}

class PairOut(BaseModel):
    id: int
    submission_a_id: int
    submission_b_id: int
    similarity_score: float
    jaccard_score: float | None
    originality_score: float | None
    fragments: list[FragmentOut] = []
    type_result: TypeResultOut | None = None
    review: "ReviewOut | None" = None
    model_config = {"from_attributes": True}


# --- Review ---

class ReviewCreate(BaseModel):
    status: ReviewStatus
    notes: str | None = None

class ReviewOut(BaseModel):
    id: int
    pair_id: int
    reviewer_id: int
    status: ReviewStatus
    notes: str | None
    decided_at: datetime
    model_config = {"from_attributes": True}


# --- Audit ---

class AuditLogOut(BaseModel):
    id: int
    user_id: int | None
    action: AuditAction
    target_id: int | None
    target_type: str | None
    detail: str | None
    ip_address: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


PairOut.model_rebuild()
