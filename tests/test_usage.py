"""Token counting and the admin usage page: numbers only, admins only, cost from entered prices."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.db.repositories import ModelCatalogRepository, UsageRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base, ModelUsageRow
from app.models.llm import CatalogEntry, NewModel, PriceChange, Provider
from app.models.usage import UsageTotal
from app.security.roles import Role
from app.usage import UsageCallback, UsageLog, summarise
from tests.helpers import person

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
MODEL = "claude-sonnet-5-5"


class ListSink:
    def __init__(self):
        self.rows = []

    def record(self, role, model, input_tokens, output_tokens):
        self.rows.append((role, model, input_tokens, output_tokens))


def result(input_tokens=0, output_tokens=0):
    message = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_the_callback_reports_the_tokens_the_provider_counted():
    sink = ListSink()
    UsageCallback("answer", MODEL, sink).on_llm_end(result(120, 30))
    assert sink.rows == [("answer", MODEL, 120, 30)]


def test_a_call_with_no_token_counts_records_nothing():
    sink = ListSink()
    UsageCallback("answer", MODEL, sink).on_llm_end(result(0, 0))
    assert sink.rows == []


def test_a_recording_problem_never_breaks_the_call():
    class Broken:
        def record(self, *args):
            raise RuntimeError("database down")

    UsageCallback("answer", MODEL, Broken()).on_llm_end(result(5, 5))


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'usage.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        ModelCatalogRepository(session).add(
            NewModel(model_id=MODEL, provider=Provider.ANTHROPIC), "system"
        )
    return engine


def log(engine, role, tokens_in, tokens_out):
    UsageLog(lambda: session_scope(engine)).record(role, MODEL, tokens_in, tokens_out)


def test_the_log_adds_up_by_task_and_model(engine):
    log(engine, "answer", 100, 20)
    log(engine, "answer", 50, 10)
    log(engine, "graph", 400, 80)
    with session_scope(engine) as session:
        totals = {(t.role, t.model): t for t in UsageRepository(session).totals(30)}
    assert totals[("answer", MODEL)].calls == 2
    assert totals[("answer", MODEL)].input_tokens == 150
    assert totals[("graph", MODEL)].output_tokens == 80


def test_old_calls_fall_outside_the_period(engine):
    log(engine, "answer", 100, 20)
    with Session(engine) as session:
        row = session.query(ModelUsageRow).one()
        row.at = row.at.replace(year=2020)
        session.commit()
    with session_scope(engine) as session:
        assert UsageRepository(session).totals(30) == []


def entry(price_in=None, price_out=None):
    return CatalogEntry(
        model_id=MODEL, provider=Provider.ANTHROPIC, key_name="K",
        input_price=price_in, output_price=price_out,
    )  # fmt: skip


def test_cost_is_tokens_times_the_price_per_million():
    totals = [UsageTotal(role="answer", model=MODEL, calls=2, input_tokens=2_000_000,
                         output_tokens=500_000)]  # fmt: skip
    summary = summarise(totals, [entry(3.0, 15.0)], 30)
    assert summary.lines[0].cost == pytest.approx(13.5)
    assert summary.cost == pytest.approx(13.5)
    assert summary.unpriced_models == []


def test_a_model_without_a_price_counts_tokens_but_not_cost():
    totals = [UsageTotal(role="answer", model=MODEL, calls=1, input_tokens=10, output_tokens=5)]
    summary = summarise(totals, [entry()], 7)
    assert summary.lines[0].cost is None
    assert (summary.calls, summary.input_tokens, summary.output_tokens) == (1, 10, 5)
    assert summary.cost == 0.0
    assert summary.unpriced_models == [MODEL]


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[current_principal] = lambda: ADMIN
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("role", [Role.MEMBER, Role.REVIEWER])
def test_only_admins_see_usage_and_set_prices(client, role):
    app.dependency_overrides[current_principal] = lambda: person(role)
    assert client.get("/admin/usage").status_code == 403
    body = {"input_price": 1, "output_price": 2}
    assert client.put(f"/admin/models/catalog/{MODEL}/price", json=body).status_code == 403


def test_usage_endpoint_shows_totals_and_estimated_cost(client, engine):
    log(engine, "answer", 1_000_000, 100_000)
    assert client.get("/admin/usage").json()["unpriced_models"] == [MODEL]
    body = {"input_price": 3.0, "output_price": 15.0}
    assert client.put(f"/admin/models/catalog/{MODEL}/price", json=body).status_code == 200
    data = client.get("/admin/usage?days=7").json()
    assert data["days"] == 7
    assert data["calls"] == 1
    assert data["cost"] == pytest.approx(4.5)
    assert data["lines"][0]["role"] == "answer"


def test_setting_a_price_is_audited_and_listed(client, engine):
    body = {"input_price": 3.0, "output_price": 15.0}
    client.put(f"/admin/models/catalog/{MODEL}/price", json=body)
    listed = client.get("/admin/models").json()["catalog"][0]
    assert (listed["input_price"], listed["output_price"]) == (3.0, 15.0)
    with Session(engine) as session:
        audit = session.query(AuditLogRow).one()
    assert audit.action == "model:price"


@pytest.mark.parametrize("bad", [{"input_price": -1, "output_price": 2}, {"input_price": 1}])
def test_a_bad_price_is_refused(client, bad):
    assert client.put(f"/admin/models/catalog/{MODEL}/price", json=bad).status_code == 422


def test_pricing_an_unknown_model_is_refused(client):
    body = {"input_price": 1, "output_price": 2}
    assert client.put("/admin/models/catalog/nope/price", json=body).status_code == 404


def test_the_period_must_be_sensible(client):
    assert client.get("/admin/usage?days=0").status_code == 422
    assert client.get("/admin/usage?days=999").status_code == 422


def test_price_change_model_rejects_extra_fields():
    with pytest.raises(ValueError, match="surprise"):
        PriceChange(input_price=1, output_price=1, surprise=1)
