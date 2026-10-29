from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.config import IntegrationNotConfiguredError, Settings
from app.db.engine import engine_from_settings, make_engine
from app.db.repositories import JobRepository
from app.db.session import session_scope
from app.db.tables import Base
from app.errors import ProviderError
from app.models.job import JobStatus, Outcome
from app.worker import MAX_ATTEMPTS, drain, process_next

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_job_lifecycle_is_persisted(engine):
    with session_scope(engine) as session:
        repo = JobRepository(session)
        assert repo.create("j1", "transcribe").status == JobStatus.QUEUED
    with session_scope(engine) as session:
        repo = JobRepository(session)
        repo.set_status("j1", JobStatus.REVIEW)
        assert repo.get("j1").status == JobStatus.REVIEW
        assert repo.get("missing") is None


def test_set_status_on_unknown_job_is_an_error(engine):
    with session_scope(engine) as session, pytest.raises(KeyError):
        JobRepository(session).set_status("nope", JobStatus.FAILED)


def test_session_rolls_back_on_error(engine):
    with pytest.raises(RuntimeError):
        _create_then_fail(engine)
    with session_scope(engine) as session:
        assert JobRepository(session).get("j1") is None


def _create_then_fail(engine):
    with session_scope(engine) as session:
        JobRepository(session).create("j1", "k")
        raise RuntimeError("boom")


def test_worker_runs_the_registered_handler(engine):
    with session_scope(engine) as session:
        JobRepository(session).create("j1", "transcribe")
    handlers = {"transcribe": lambda job: Outcome(status=JobStatus.REVIEW)}
    assert process_next(engine, handlers)
    assert not process_next(engine, handlers)
    assert job_state(engine, "j1") == (JobStatus.REVIEW, None, 1)


def job_state(engine, job_id):
    with session_scope(engine) as session:
        job = JobRepository(session).get(job_id)
    return job.status, job.error, job.attempts


def test_worker_fails_jobs_without_a_handler(engine):
    with session_scope(engine) as session:
        JobRepository(session).create("j1", "mystery")
    process_next(engine, {})
    assert job_state(engine, "j1") == (JobStatus.FAILED, "no_handler", 1)


def test_provider_errors_are_retried_a_bounded_number_of_times(engine):
    def broken(job):
        raise ProviderError("secret detail", code="asr")

    with session_scope(engine) as session:
        JobRepository(session).create("j1", "k")
    states = []
    for _ in range(MAX_ATTEMPTS):
        process_next(engine, {"k": broken})
        states.append(job_state(engine, "j1"))
    assert [s[0] for s in states] == [JobStatus.QUEUED] * (MAX_ATTEMPTS - 1) + [JobStatus.FAILED]
    assert states[-1] == (JobStatus.FAILED, "asr", MAX_ATTEMPTS)
    assert not process_next(engine, {"k": broken})


def test_an_unexpected_crash_fails_the_job_instead_of_killing_the_worker(engine):
    def crash(job):
        raise RuntimeError("bug with private detail")

    with session_scope(engine) as session:
        JobRepository(session).create("j1", "k")
    assert process_next(engine, {"k": crash})
    assert job_state(engine, "j1") == (JobStatus.FAILED, "internal", 1)


def test_a_handler_can_update_progress_while_its_job_is_claimed(engine):
    def handler(job):
        with session_scope(engine) as session:
            JobRepository(session).set_stage(job.id, "transcribing")
        return Outcome(status=JobStatus.REVIEW)

    with session_scope(engine) as session:
        JobRepository(session).create("j1", "k")
    process_next(engine, {"k": handler})
    with session_scope(engine) as session:
        assert JobRepository(session).get("j1").stage == "transcribing"


def test_drain_once_exits_when_the_queue_is_empty(engine):
    drain(engine, once=True)


def test_engine_requires_a_database_url(monkeypatch):
    monkeypatch.delenv("HERITAGEVOICE_DATABASE_URL", raising=False)
    with pytest.raises(IntegrationNotConfiguredError):
        engine_from_settings(Settings(_env_file=None))


def test_migrations_create_the_job_table(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("HERITAGEVOICE_DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
    assert "job" in inspect(create_engine(url)).get_table_names()
    command.downgrade(config, "base")
    assert "job" not in inspect(create_engine(url)).get_table_names()


def test_migrations_match_the_table_definitions(tmp_path, monkeypatch):
    """Guards drift: every table and column in the models exists after `alembic upgrade head`."""
    url = f"sqlite:///{tmp_path / 'drift.db'}"
    monkeypatch.setenv("HERITAGEVOICE_DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
    inspector = inspect(create_engine(url))
    for table in Base.metadata.sorted_tables:
        migrated = {c["name"] for c in inspector.get_columns(table.name)}
        assert migrated == {c.name for c in table.columns}, table.name
