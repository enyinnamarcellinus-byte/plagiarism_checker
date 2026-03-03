import os
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, lecturer_or_admin
from ..config import settings
from ..database import get_db
from ..models import Exam, JobStatus, PlagiarismJob, Role, Submission, User
from ..schemas import JobOut, SubmissionOut
from ..services.crypto import decrypt_file, encrypt_file
from ..services.extraction import extract_text

router = APIRouter(prefix="/submissions", tags=["submissions"])


def _save_file(file: UploadFile, exam: Exam) -> str:
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in exam.allowed_formats.split(","):
        raise HTTPException(status_code=400, detail=f"File type .{ext} not allowed for this exam")

    dest_dir = os.path.join(settings.upload_dir, str(exam.id))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{uuid.uuid4()}.{ext}")

    max_bytes = exam.max_file_mb * 1024 * 1024
    size = 0
    with open(dest, "wb") as f:
        while chunk := file.file.read(8192):
            size += len(chunk)
            if size > max_bytes:
                f.close()
                os.remove(dest)
                raise HTTPException(
                    status_code=413, detail=f"File exceeds {exam.max_file_mb}MB limit"
                )
            f.write(chunk)
    return dest


def _upsert_job(exam_id: int, db: Session) -> PlagiarismJob:
    job = db.query(PlagiarismJob).filter_by(exam_id=exam_id).first()
    if job:
        job.status = JobStatus.pending
        job.error = None
        job.celery_id = None
        job.finished_at = None
        job.queued_at = datetime.now(UTC)
    else:
        job = PlagiarismJob(exam_id=exam_id)
        db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/{exam_id}", response_model=SubmissionOut, status_code=status.HTTP_201_CREATED)
async def upload_submission(
    exam_id: int,
    file: UploadFile,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if user.role != Role.student:
        raise HTTPException(status_code=403, detail="Only students can submit")

    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    now = datetime.now(UTC)
    if not (exam.opens_at <= now.replace(tzinfo=None) <= exam.closes_at):
        raise HTTPException(status_code=400, detail="Submission window is not open")

    file_path = _save_file(file, exam)
    encrypt_file(file_path)
    raw_bytes = decrypt_file(file_path)
    ext = file_path.rsplit(".", 1)[-1].lower()
    text = extract_text(raw_bytes, ext)

    submission = Submission(
        exam_id=exam_id,
        student_id=user.id,
        file_path=file_path,
        extracted_text=text,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    job = _upsert_job(exam_id, db)
    from ..tasks.analysis import run_plagiarism_analysis

    task = run_plagiarism_analysis.delay(exam_id)
    job.celery_id = task.id
    db.commit()

    return submission


@router.get("/{exam_id}", response_model=list[SubmissionOut])
def list_submissions(
    exam_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam.lecturer_id != user.id and user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Not your exam")
    return db.query(Submission).filter_by(exam_id=exam_id).all()


@router.get("/{exam_id}/job", response_model=JobOut)
def get_job_status(
    exam_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(lecturer_or_admin)],
):
    job = db.query(PlagiarismJob).filter_by(exam_id=exam_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="No analysis job found for this exam")
    return job
