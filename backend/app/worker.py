import logging
from time import sleep

from app.config import get_settings
from app.database import SessionLocal
from app.services.ai_engine import build_ai_engine_client
from app.services.job_worker import claim_next_job, process_job


logger = logging.getLogger(__name__)


def run_once() -> bool:
    settings = get_settings()
    ai_client = build_ai_engine_client(settings)

    with SessionLocal() as session:
        job = claim_next_job(session)

        if job is None:
            logger.debug("No queued jobs found")
            return False

        try:
            result = process_job(
                session=session,
                job=job,
                ai_client=ai_client,
                upload_dir=settings.upload_dir,
            )
        except Exception:
            logger.exception("Job %s failed", job.id)
            return True

        logger.info(
            "Job %s succeeded with engine %s",
            job.id,
            result.engine_version,
        )
        return True


def run_forever() -> None:
    settings = get_settings()

    while True:
        handled_job = run_once()

        if not handled_job:
            sleep(settings.worker_poll_interval_seconds)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        run_forever()
    except KeyboardInterrupt:
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
