"""Background worker: claims queued jobs and runs the handler registered for their kind.

Run with: uv run python -m app.worker   (add --once to process the queue and exit)

The claim is committed before the handler runs, so a handler can update the job's progress from
its own transaction without waiting on the worker's lock. A provider failure puts the job back
in the queue until `MAX_ATTEMPTS` is reached, then fails it with a safe code. Jobs without a
handler fail with `no_handler` instead of being silently dropped.
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
from app.models.job import Job, JobStatus, Outcome
from app.worker_setup import build_handlers

logger = logging.getLogger("heritagevoice.worker")
POLL_SECONDS = 2.0
MAX_ATTEMPTS = 3

Handler = Callable[[Job], Outcome]
HANDLERS: dict[str, Handler] = {}


def _provider_outcome(job: Job, error: ProviderError) -> Outcome:
    if job.attempts < MAX_ATTEMPTS:
        return Outcome(status=JobStatus.QUEUED)
    return Outcome(status=JobStatus.FAILED, error=error.code)


def _call(job: Job, handler: Handler) -> Outcome:
    try:
        return handler(job)
    except ProviderError as error:
        return _provider_outcome(job, error)
    except Exception:
        logger.exception("job %s (%s) crashed", job.id, job.kind)
        return Outcome(status=JobStatus.FAILED, error="internal")


def _run_handler(job: Job, handlers: Mapping[str, Handler]) -> Outcome:
    handler = handlers.get(job.kind)
    if handler is None:
        return Outcome(status=JobStatus.FAILED, error="no_handler")
    return _call(job, handler)


def process_next(engine: Engine, handlers: Mapping[str, Handler]) -> bool:
    with session_scope(engine) as session:
        job = JobRepository(session).claim_next_queued()
    if job is None:
        return False
    outcome = _run_handler(job, handlers)
    with session_scope(engine) as session:
        JobRepository(session).set_status(job.id, outcome.status, outcome.error)
    logger.info("job %s (%s) attempt %s -> %s", job.id, job.kind, job.attempts, outcome.status)
    return True


def drain(engine: Engine, once: bool, handlers: Mapping[str, Handler] = HANDLERS) -> None:
    while True:
        worked = process_next(engine, handlers)
        if once and not worked:
            return
        if not worked:
            time.sleep(POLL_SECONDS)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="HeritageVoice background worker")
    parser.add_argument("--once", action="store_true", help="process queued jobs, then exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    engine = engine_from_settings(settings)
    drain(engine, args.once, build_handlers(settings, engine))


if __name__ == "__main__":
    main()
