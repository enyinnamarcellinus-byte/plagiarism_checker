from datetime import datetime, timezone
from celery import Celery
from ..config import settings

celery_app = Celery("plagiarism")
celery_app.config_from_object("celeryconfig")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_plagiarism_analysis(self, exam_id: int):
    """
    Full pipeline for one exam:
      1. load all submissions with extracted text
      2. bulk pairwise similarity
      3. for each flagged pair: persist SimilarityPair + fragments + type result
    Previous results for this exam are wiped before writing new ones (idempotent).
    """
    from ..database import SessionLocal
    from ..models import (
        JobStatus, MatchedFragment, PlagiarismJob,
        PlagiarismTypeResult, SimilarityPair, Submission,
    )
    from ..services.similarity import bulk_compare
    from ..services.classifier import classify

    db = SessionLocal()
    job = db.query(PlagiarismJob).filter_by(exam_id=exam_id).first()

    try:
        job.status = JobStatus.running
        db.commit()

        submissions = (
            db.query(Submission)
            .filter(Submission.exam_id == exam_id, Submission.extracted_text.isnot(None))
            .all()
        )

        texts = {s.id: s.extracted_text for s in submissions}

        # Wipe previous results so re-runs are idempotent
        existing_pairs = db.query(SimilarityPair).filter(
            SimilarityPair.submission_a_id.in_(texts.keys())
        ).all()
        for p in existing_pairs:
            db.delete(p)
        db.commit()

        pairs = bulk_compare(texts)

        for sub_a_id, sub_b_id, result in pairs:
            pair = SimilarityPair(
                submission_a_id=sub_a_id,
                submission_b_id=sub_b_id,
                similarity_score=result.score,
            )
            db.add(pair)
            db.flush()  # get pair.id without full commit

            for frag in result.fragments:
                db.add(MatchedFragment(
                    pair_id=pair.id,
                    text=frag.text,
                    start_a=frag.start_a, end_a=frag.end_a,
                    start_b=frag.start_b, end_b=frag.end_b,
                    length=frag.length,
                ))

            sub_a = next(s for s in submissions if s.id == sub_a_id)
            sub_b = next(s for s in submissions if s.id == sub_b_id)
            token_count_a = len(sub_a.extracted_text.split())
            token_count_b = len(sub_b.extracted_text.split())

            classification = classify(result.fragments, result.score, token_count_a, token_count_b)
            db.add(PlagiarismTypeResult(
                pair_id=pair.id,
                predicted_type=classification.predicted_type,
                score_verbatim=classification.score_verbatim,
                score_near_copy=classification.score_near_copy,
                score_patchwork=classification.score_patchwork,
                score_structural=classification.score_structural,
            ))

        job.status = JobStatus.completed
        job.finished_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        db.rollback()
        job.status = JobStatus.failed
        job.error = str(exc)
        db.commit()
        raise self.retry(exc=exc)

    finally:
        db.close()