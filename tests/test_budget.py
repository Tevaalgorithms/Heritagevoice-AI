"""The monthly cost limit: spent as a daily share, checked before every model call."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.budget import (
    BUDGET,
    BudgetExceededError,
    GuardedUsageLog,
    budget_status,
    check_budget,
    daily_share,
)
from app.db.repositories import CostLimitRepository, ModelCatalogRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.errors import ProviderError
from app.models.job import Job, JobStatus
from app.models.llm import NewModel, PriceChange, Provider
from app.security.roles import Role
from app.usage import UsageCallback
from app.worker import _provider_outcome
from tests.helpers import person

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
MODEL = "claude-sonnet-5-5"
NOON = datetime(2026, 11, 7, 12, tzinfo=UTC)  # November has 30 days


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'budget.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        catalog = ModelCatalogRepository(session)
        catalog.add(NewModel(model_id=MODEL, provider=Provider.ANTHROPIC), "system")
        catalog.set_price(MODEL, PriceChange(input_price=1.0, output_price=1.0))
    return engine


def sessions(engine):
    return lambda: session_scope(engine)


def limit(engine, monthly):
    with session_scope(engine) as session:
        CostLimitRepository(session).set(monthly, "admin-1")


def spend(engine, dollars):
    """Record calls that cost about this many dollars at $1 per million tokens."""
    GuardedUsageLog(sessions(engine)).record("answer", MODEL, int(dollars * 1_000_000), 0)


def test_a_day_gets_the_monthly_limit_divided_by_the_days_of_that_month():
    assert daily_share(30.0, NOON) == pytest.approx(1.0)  # November: 30 days
    assert daily_share(31.0, datetime(2026, 12, 3, tzinfo=UTC)) == pytest.approx(1.0)
    assert daily_share(29.0, datetime(2028, 2, 3, tzinfo=UTC)) == pytest.approx(1.0)  # leap year


def test_with_no_limit_nothing_is_ever_blocked(engine):
    spend(engine, 500)
    status = budget_status(sessions(engine))
    assert status.monthly_usd is None
    assert status.daily_usd is None
    assert not status.exhausted
    check_budget(sessions(engine))


def test_the_status_shows_today_s_share_spent_and_left(engine):
    limit(engine, 30.0)
    spend(engine, 0.25)
    status = budget_status(sessions(engine))
    assert status.daily_usd == pytest.approx(daily_share(30.0, datetime.now(UTC)))
    assert status.spent_today == pytest.approx(0.25)
    assert status.remaining_today == pytest.approx(status.daily_usd - 0.25)
    assert not status.exhausted


def test_once_the_days_share_is_spent_the_next_call_is_refused(engine):
    limit(engine, 30.0)
    spend(engine, 100.0)
    assert budget_status(sessions(engine)).exhausted
    with pytest.raises(BudgetExceededError) as refused:
        check_budget(sessions(engine))
    assert refused.value.code == BUDGET
    assert isinstance(refused.value, ProviderError)


def test_spending_from_an_earlier_day_does_not_count_today(engine):
    from app.db.tables import ModelUsageRow  # noqa: PLC0415

    limit(engine, 30.0)
    spend(engine, 100.0)
    with Session(engine) as session:
        row = session.query(ModelUsageRow).one()
        row.at = row.at.replace(year=2020)
        session.commit()
    assert not budget_status(sessions(engine)).exhausted


def test_a_model_without_a_price_is_not_counted_and_is_named(engine):
    limit(engine, 30.0)
    with session_scope(engine) as session:
        ModelCatalogRepository(session).add(
            NewModel(model_id="cheap-new", provider=Provider.OPENAI), "system"
        )
    GuardedUsageLog(sessions(engine)).record("answer", "cheap-new", 9_000_000, 0)
    status = budget_status(sessions(engine))
    assert status.spent_today == 0
    assert status.unpriced_models == ["cheap-new"]


def test_the_model_is_never_called_once_the_budget_is_spent(engine):
    limit(engine, 30.0)
    spend(engine, 100.0)
    model = FakeListChatModel(
        responses=["hello"],
        callbacks=[UsageCallback("answer", MODEL, GuardedUsageLog(sessions(engine)))],
    )
    with pytest.raises(BudgetExceededError):
        model.invoke("hi")
    assert model.i == 0  # the fake's counter: the provider was never reached


def test_the_model_is_called_while_there_is_budget_left(engine):
    limit(engine, 30.0)
    model = FakeListChatModel(
        responses=["hello"],
        callbacks=[UsageCallback("answer", MODEL, GuardedUsageLog(sessions(engine)))],
    )
    assert model.invoke("hi").content == "hello"


def test_a_job_blocked_by_the_budget_is_not_retried_today():
    job = Job(id="j1", kind="x", attempts=1, status=JobStatus.PROCESSING)
    outcome = _provider_outcome(job, BudgetExceededError())
    assert outcome.status is JobStatus.FAILED
    assert outcome.error == BUDGET
    assert _provider_outcome(job, ProviderError("x", code="mt")).status is JobStatus.QUEUED


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[current_principal] = lambda: ADMIN
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("role", [Role.MEMBER, Role.REVIEWER])
def test_only_admins_see_or_change_the_limit(client, role):
    app.dependency_overrides[current_principal] = lambda: person(role)
    assert client.get("/admin/budget").status_code == 403
    assert client.put("/admin/budget", json={"monthly_usd": 10}).status_code == 403


def test_an_admin_sets_reads_and_removes_the_limit_with_an_audit_record(client, engine):
    assert client.get("/admin/budget").json()["monthly_usd"] is None
    saved = client.put("/admin/budget", json={"monthly_usd": 10}).json()
    assert saved["monthly_usd"] == 10
    assert saved["daily_usd"] > 0
    assert client.get("/admin/budget").json()["monthly_usd"] == 10
    assert client.put("/admin/budget", json={"monthly_usd": None}).json()["monthly_usd"] is None
    with Session(engine) as session:
        actions = [row.action for row in session.query(AuditLogRow)]
    assert actions == ["budget:set", "budget:set"]


@pytest.mark.parametrize("bad", [{"monthly_usd": 0}, {"monthly_usd": -5}, {}, {"monthly_usd": "x"}])
def test_a_nonsense_limit_is_refused(client, bad):
    assert client.put("/admin/budget", json=bad).status_code == 422
