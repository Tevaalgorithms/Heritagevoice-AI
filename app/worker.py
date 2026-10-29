"""Background worker: claims queued jobs and runs the handler registered for their kind.

Run with: uv run python -m app.worker   (add --once to process the queue and exit)
Handlers are added by later segments (transcription, indexing); until then every job fails
with the safe code `no_handler` rather than being silently dropped.
"""

import argparse
import logging
import time
from collections.abc import Callable, Mapping, Sequence

from sqlalchemy import Engine

from app.config import Settings
from app.db.engine import engine_from_settings
from app.db.repositories import JobRepository
from app.db.session import session_scope
from app.errors import ProviderError
from app.models.job import Job, JobStatus

logger = logging.getLogger("heritagevoice.worker")
POLL_SECONDS = 2.0

Handler = Callable[[Job], JobStatus]
HANDLERS: dict[str, Handler] = {}


def _run_handler(job: Job, handlers: Mapping[str, Handler]) -> tuple[JobStatus, str | None]:
    handler = handlers.get(job.kind)
    if handler is None:
        return JobStatus.FAILED, "no_handler"
    try:
        return handler(job), None
    except ProviderError:
        return JobStatus.FAILED, "provider"


def process_next(repo: JobRepository, handlers: Mapping[str, Handler]) -> bool:
    job = repo.claim_next_queued()
    if job is None:
        return False
    status, error = _run_handler(job, handlers)
    repo.set_status(job.id, status, error)
    logger.info("job %s (%s) -> %s", job.id, job.kind, status)
    return True


def drain(engine: Engine, once: bool) -> None:
    while True:
        with session_scope(engine) as session:
            worked = process_next(JobRepository(session), HANDLERS)
        if once and not worked:
            return
        if not worked:
            time.sleep(POLL_SECONDS)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="HeritageVoice background worker")
    parser.add_argument("--once", action="store_true", help="process queued jobs, then exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    drain(engine_from_settings(Settings()), args.once)


if __name__ == "__main__":
    main()
