"""The open Library: what a visitor with no account may and may not see."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.public import MAX_LIMIT, get_limiter
from app.db.repositories import ConsentRepository, RecordingRepository
from app.db.session import session_scope
from app.db.tables import Base, ConsentRow
from app.indexing import IndexDeps, index_one
from app.models.records import REMEDY_NOTICE, HeritageKind, RecordingStatus, Right, Visibility
from app.ratelimit import SlidingWindowLimiter
from tests.index_helpers import published

URL = "/v1/public/library"
WITHOUT_CREDIT = [r for r in Right if r is not Right.ATTRIBUTION]


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'public.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def visitor(engine):
    """A client with no credentials at all."""
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    limiter = SlidingWindowLimiter(1000, 60.0)
    app.dependency_overrides[get_limiter] = lambda: limiter
    yield TestClient(app)
    app.dependency_overrides.clear()


def add(engine, recording_id="r1", community="c2", **options):
    with session_scope(engine) as session:
        published(session, recording_id, community, **options)
    index_one(IndexDeps(lambda: session_scope(engine)), recording_id)


def ids(response):
    assert response.status_code == 200, response.text
    return [i["recording_id"] for i in response.json()["items"]]


def test_a_visitor_with_no_account_can_browse_and_search_public_recordings(visitor, engine):
    add(engine, visibility=Visibility.PUBLIC)
    assert ids(visitor.get(URL)) == ["r1"]
    assert ids(visitor.get(URL, params={"q": "water", "view": "translation"})) == ["r1"]
    assert ids(visitor.get(URL, params={"q": "தண்ணீர்"})) == ["r1"]


def test_a_community_only_recording_is_never_shown_to_a_visitor(visitor, engine):
    add(engine, visibility=Visibility.COMMUNITY)
    assert ids(visitor.get(URL)) == []
    assert ids(visitor.get(URL, params={"q": "water", "view": "translation"})) == []


def test_public_needs_the_communitys_public_sharing_consent(visitor, engine):
    without = [r for r in Right if r is not Right.PUBLIC_SHARING]
    add(engine, visibility=Visibility.PUBLIC, consent={"rights": without})
    assert ids(visitor.get(URL)) == []


def test_withdrawn_consent_hides_a_recording_from_visitors_at_once(visitor, engine):
    add(engine, visibility=Visibility.PUBLIC)
    assert ids(visitor.get(URL)) == ["r1"]
    with session_scope(engine) as session:
        ConsentRepository(session).revoke("consent-1")
    assert ids(visitor.get(URL)) == []
    assert ids(visitor.get(URL, params={"q": "water", "view": "translation"})) == []


def test_a_recording_taken_out_of_publication_disappears_for_visitors(visitor, engine):
    add(engine, visibility=Visibility.PUBLIC)
    with session_scope(engine) as session:
        RecordingRepository(session).set_status("r1", RecordingStatus.REVIEW)
    assert ids(visitor.get(URL)) == []


def test_dropping_only_the_public_sharing_right_hides_it_from_visitors(visitor, engine):
    add(engine, visibility=Visibility.PUBLIC)
    with session_scope(engine) as session:
        row = session.get(ConsentRow, "consent-1")
        row.rights = [r for r in row.rights if r != Right.PUBLIC_SHARING.value]
    assert ids(visitor.get(URL)) == []


def test_a_remedy_carries_its_notice_for_visitors_too(visitor, engine):
    add(engine, "r-remedy", visibility=Visibility.PUBLIC, kind=HeritageKind.REMEDY)
    (item,) = visitor.get(URL).json()["items"]
    assert item["notices"] == [REMEDY_NOTICE]


def test_a_visitor_sees_no_uploader_audio_location_or_consent_details(visitor, engine):
    add(engine, visibility=Visibility.PUBLIC)
    text = (
        visitor.get(URL).text + visitor.get(URL, params={"q": "water", "view": "translation"}).text
    )
    for leaked in ("uploader", "audio_key", "recordings/", "consent", "community:"):
        assert leaked not in text


def test_the_community_is_named_only_when_the_consent_allows_credit(visitor, engine):
    add(engine, "r-credit", visibility=Visibility.PUBLIC)
    add(
        engine,
        "r-anon",
        visibility=Visibility.PUBLIC,
        consent_id="c-anon",
        consent={"rights": WITHOUT_CREDIT},
    )
    items = {i["recording_id"]: i["community"] for i in visitor.get(URL).json()["items"]}
    assert items == {"r-credit": "c2", "r-anon": None}


def test_language_kind_and_form_filters_work_for_visitors(visitor, engine):
    add(engine, "r-ta", visibility=Visibility.PUBLIC, kind=HeritageKind.SONG)
    add(engine, "r-hi", visibility=Visibility.PUBLIC, language="hi", kind=HeritageKind.STORY)
    assert ids(visitor.get(URL, params={"language": "hi"})) == ["r-hi"]
    assert ids(visitor.get(URL, params={"kind": "song"})) == ["r-ta"]
    original = visitor.get(URL, params={"language": "ta"}).json()["items"][0]
    assert original["view"] == "original"


def test_nothing_is_kept_by_browsers_proxies_or_search_engines(visitor, engine):
    add(engine, visibility=Visibility.PUBLIC)
    headers = visitor.get(URL).headers
    assert headers["cache-control"] == "no-store"
    assert headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.parametrize(
    "params",
    [
        {"limit": MAX_LIMIT + 1},
        {"limit": 0},
        {"q": "x" * 101},
        {"kind": "x"},
        {"language": "TA"},
        {"role": "admin"},
    ],
    ids=["too-many", "none", "long-query", "bad-kind", "bad-language", "extra"],
)
def test_bad_parameters_are_rejected(visitor, params):
    assert visitor.get(URL, params=params).status_code == 422


def test_visitors_get_small_pages(visitor, engine):
    for index in range(MAX_LIMIT + 5):
        add(engine, f"r{index}", visibility=Visibility.PUBLIC)
    assert len(ids(visitor.get(URL))) == 10
    assert len(ids(visitor.get(URL, params={"limit": MAX_LIMIT}))) == MAX_LIMIT


# --- the limit on a service that needs no sign-in --------------------------------------------


def test_a_visitor_who_asks_too_often_is_told_to_wait(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    limiter = SlidingWindowLimiter(3, 60.0)
    app.dependency_overrides[get_limiter] = lambda: limiter
    client = TestClient(app)
    codes = [client.get(URL).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    blocked = client.get(URL)
    assert blocked.json()["detail"] == {"code": "rate_limited"}
    assert int(blocked.headers["retry-after"]) >= 1
    app.dependency_overrides.clear()


def test_each_visitor_has_their_own_allowance(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    limiter = SlidingWindowLimiter(1, 60.0)
    app.dependency_overrides[get_limiter] = lambda: limiter
    client = TestClient(app)
    first = {"x-forwarded-for": "203.0.113.1"}
    second = {"x-forwarded-for": "203.0.113.2"}
    assert client.get(URL, headers=first).status_code == 200
    assert client.get(URL, headers=first).status_code == 429
    assert client.get(URL, headers=second).status_code == 200
    app.dependency_overrides.clear()


def test_the_limiter_forgets_old_calls():
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 10.0, clock=lambda: now[0])
    assert [limiter.allow("a") for _ in range(3)] == [True, True, False]
    now[0] = 11.0
    assert limiter.allow("a") is True


def test_the_limiter_never_grows_without_bound():
    from app import ratelimit  # noqa: PLC0415

    limiter = SlidingWindowLimiter(5, 60.0)
    for index in range(ratelimit.MAX_KEYS + 50):
        limiter.allow(f"k{index}")
    assert len(limiter._calls) <= ratelimit.MAX_KEYS


# --- everything else still needs an account --------------------------------------------------


def test_the_other_endpoints_stay_closed_to_visitors(visitor):
    app.dependency_overrides.pop(current_principal, None)
    for method, path in (("get", "/v1/library"), ("post", "/v1/query"), ("get", "/v1/recordings")):
        response = getattr(visitor, method)(path)
        assert response.status_code in {401, 503}, path
    assert visitor.post("/v1/recordings").status_code in {401, 422, 503}
    assert visitor.get("/admin/models").status_code in {401, 503}


def test_a_query_cannot_make_a_visitor_see_what_a_member_would(visitor, engine):
    add(engine, "r-private", "c2", visibility=Visibility.COMMUNITY)
    add(engine, "r-public", "c2", consent_id="consent-2", visibility=Visibility.PUBLIC)
    for params in ({}, {"q": "water", "view": "translation"}, {"q": "r-private"}):
        assert "r-private" not in ids(visitor.get(URL, params=params))
