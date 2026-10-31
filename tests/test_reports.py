import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.reports import get_limiter
from app.db.repositories import RecordingRepository, ReportRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base, ItemReportRow, JobRow
from app.indexing import IndexDeps, index_one
from app.models.records import RecordingStatus, ReportStatus, Visibility
from app.ratelimit import SlidingWindowLimiter
from app.security.roles import Role
from tests.helpers import person
from tests.index_helpers import published

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
MEMBER = person(Role.MEMBER, user_id="member-1", communities=("c1",))
OUTSIDER = person(Role.MEMBER, user_id="out-1", communities=("c9",))


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reports.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    limiter = SlidingWindowLimiter(5, 3600.0)
    app.dependency_overrides[get_limiter] = lambda: limiter
    app.dependency_overrides[current_principal] = lambda: MEMBER
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def seed(engine, **content):
    with session_scope(engine) as session:
        published(session, **content)
    index_one(IndexDeps(lambda: session_scope(engine)), "r1")


def report(client, path="/v1/public/report", **body):
    return client.post(path, json={"recording_id": "r1", "reason": "private", **body})


def rows(engine):
    with Session(engine) as session:
        return session.scalars(select(ItemReportRow)).all()


def test_a_visitor_can_report_a_public_recording_without_an_account(client, engine):
    seed(engine, visibility=Visibility.PUBLIC)
    response = report(client, note="  This is my grandmother's private prayer.  ")
    assert response.status_code == 201
    (saved,) = rows(engine)
    assert (saved.reporter, saved.status) == (None, "open")
    assert saved.note == "This is my grandmother's private prayer."


def test_a_visitor_cannot_report_or_learn_about_a_private_recording(client, engine):
    seed(engine)  # shared with the community only
    assert report(client).status_code == 404
    assert rows(engine) == []


def test_a_member_can_report_what_their_group_shares(client, engine):
    seed(engine)
    assert report(client, "/v1/reports").status_code == 201
    assert rows(engine)[0].reporter == "member-1"
    act_as(OUTSIDER)
    assert report(client, "/v1/reports").status_code == 404


@pytest.mark.parametrize("status", [RecordingStatus.REVIEW, RecordingStatus.REVOKED])
def test_only_published_recordings_can_be_reported(client, engine, status):
    seed(engine, visibility=Visibility.PUBLIC)
    with session_scope(engine) as session:
        RecordingRepository(session).set_status("r1", status)
    assert report(client).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"reason": "spam"},
        {"recording_id": "../x"},
        {"note": "x" * 501},
        {"extra": 1},
    ],
)
def test_bad_reports_are_refused(client, engine, body):
    seed(engine, visibility=Visibility.PUBLIC)
    assert report(client, **body).status_code == 422


def test_reporting_is_limited_per_visitor(client, engine):
    seed(engine, visibility=Visibility.PUBLIC)
    codes = [report(client).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]
    assert len(rows(engine)) == 5


def test_only_admins_see_reports_and_the_reporter(client, engine):
    seed(engine, visibility=Visibility.PUBLIC)
    report(client, "/v1/reports", note="please remove")
    assert client.get("/v1/admin/reports").status_code == 403
    act_as(ADMIN)
    (item,) = client.get("/v1/admin/reports").json()
    assert (item["reporter"], item["note"], item["reports_for_recording"]) == (
        "member-1",
        "please remove",
        1,
    )
    assert item["opening"].startswith("கோடையில்")


def test_taking_it_down_withdraws_the_recording_and_closes_every_report(client, engine):
    seed(engine, visibility=Visibility.PUBLIC)
    report(client)
    report(client)
    act_as(ADMIN)
    first = client.get("/v1/admin/reports").json()[0]["id"]
    response = client.post(f"/v1/admin/reports/{first}/decision", json={"action": "take_down"})
    assert response.json()["status"] == "taken_down"
    with Session(engine) as session:
        assert RecordingRepository(session).get("r1").status is RecordingStatus.REVOKED
        assert {r.status for r in session.scalars(select(ItemReportRow))} == {"taken_down"}
        assert "unindex_recording" in {j.kind for j in session.scalars(select(JobRow))}
        entry = session.scalars(select(AuditLogRow)).one()
    assert (entry.action, entry.target) == ("report:taken_down", f"report:{first}")


def test_keeping_it_leaves_the_recording_alone(client, engine):
    seed(engine, visibility=Visibility.PUBLIC)
    report(client)
    act_as(ADMIN)
    rid = client.get("/v1/admin/reports").json()[0]["id"]
    assert (
        client.post(f"/v1/admin/reports/{rid}/decision", json={"action": "dismiss"}).status_code
        == 200
    )
    with Session(engine) as session:
        assert RecordingRepository(session).get("r1").status is RecordingStatus.PUBLISHED
        assert ReportRepository(session).with_status(ReportStatus.DISMISSED)[0].id == rid
    assert client.get("/v1/admin/reports").json() == []


def test_a_decided_or_unknown_report_cannot_be_decided_again(client, engine):
    seed(engine, visibility=Visibility.PUBLIC)
    report(client)
    act_as(ADMIN)
    rid = client.get("/v1/admin/reports").json()[0]["id"]
    body = {"action": "dismiss"}
    assert client.post(f"/v1/admin/reports/{rid}/decision", json=body).status_code == 200
    assert client.post(f"/v1/admin/reports/{rid}/decision", json=body).status_code == 404
    assert client.post("/v1/admin/reports/nope/decision", json=body).status_code == 404


def test_only_admins_decide(client, engine):
    seed(engine, visibility=Visibility.PUBLIC)
    report(client)
    rid = rows(engine)[0].id
    assert (
        client.post(f"/v1/admin/reports/{rid}/decision", json={"action": "take_down"}).status_code
        == 403
    )
