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
from app.models.job import JobStatus
from app.worker import drain, process_next

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
        repo = JobRepository(session)
        repo.create("j1", "transcribe")
        assert process_next(repo, {"transcribe": lambda job: JobStatus.REVIEW})
        assert repo.get("j1").status == JobStatus.REVIEW
        assert not process_next(repo, {})


def test_worker_fails_jobs_without_a_handler(engine):
    with session_scope(engine) as session:
        repo = JobRepository(session)
        repo.create("j1", "mystery")
        process_next(repo, {})
        job = repo.get("j1")
    assert (job.status, job.error) == (JobStatus.FAILED, "no_handler")


def test_worker_turns_provider_errors_into_a_safe_code(engine):
    def broken(job):
        raise ProviderError("secret detail")

    with session_scope(engine) as session:
        repo = JobRepository(session)
        repo.create("j1", "k")
        process_next(repo, {"k": broken})
        job = repo.get("j1")
    assert (job.status, job.error) == (JobStatus.FAILED, "provider")


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
