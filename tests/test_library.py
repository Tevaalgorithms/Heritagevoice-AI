"""Who can see what in the Library. Each test is a way someone might see what they should not."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.db.repositories import ChunkRepository, ConsentRepository, RecordingRepository
from app.db.session import session_scope
from app.db.tables import Base, ConsentRow
from app.indexing import IndexDeps, index_one
from app.models.records import REMEDY_NOTICE, HeritageKind, RecordingStatus, Right, Visibility
from app.security.roles import Role
from tests.helpers import person
from tests.index_helpers import published

WITHOUT_PUBLIC = [right for right in Right if right is not Right.PUBLIC_SHARING]
WITHOUT_CREDIT = [right for right in Right if right is not Right.ATTRIBUTION]
INSIDER = person(Role.MEMBER, user_id="insider", communities=("c2",))
OUTSIDER = person(Role.MEMBER, user_id="outsider", communities=("c1",))
NO_COMMUNITY = person(Role.MEMBER, user_id="visitor", communities=())
ADMIN = person(Role.ADMIN, user_id="admin", communities=())


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'library.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[current_principal] = lambda: OUTSIDER
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def add(engine, recording_id="r2", community="c2", **options):
    """A published, indexed recording that belongs to community c2 unless said otherwise."""
    with session_scope(engine) as session:
        published(session, recording_id, community, **options)
    index_one(IndexDeps(lambda: session_scope(engine)), recording_id)


def ids(response):
    assert response.status_code == 200, response.text
    return [item["recording_id"] for item in response.json()["items"]]


def browse(client, **params):
    return client.get("/v1/library", params=params)


# --- who can see a public recording -------------------------------------------------------


def test_a_public_recording_is_visible_to_a_signed_in_user_from_another_community(client, engine):
    add(engine, visibility=Visibility.PUBLIC)
    assert ids(browse(client)) == ["r2"]
    assert ids(browse(client, q="water")) == []  # original is Tamil; searching the translation:
    assert ids(browse(client, q="water", view="translation")) == ["r2"]


def test_a_user_who_belongs_to_no_community_can_still_read_public_recordings(client, engine):
    add(engine, visibility=Visibility.PUBLIC)
    act_as(NO_COMMUNITY)
    assert ids(browse(client)) == ["r2"]
    assert ids(browse(client, q="water", view="translation")) == ["r2"]


def test_a_community_only_recording_is_invisible_to_outsiders_and_visible_to_its_members(
    client, engine
):
    add(engine, visibility=Visibility.COMMUNITY)
    for outsider in (OUTSIDER, NO_COMMUNITY):
        act_as(outsider)
        assert ids(browse(client)) == []
        assert ids(browse(client, q="water", view="translation")) == []
    act_as(INSIDER)
    assert ids(browse(client)) == ["r2"]


def test_public_needs_the_communitys_public_sharing_consent(client, engine):
    # The recording asks to be public, but its consent never allowed public sharing.
    add(engine, visibility=Visibility.PUBLIC, consent={"rights": WITHOUT_PUBLIC})
    assert ids(browse(client)) == []
    assert ids(browse(client, q="water", view="translation")) == []
    with Session(engine) as session:
        chunks = ChunkRepository(session).for_communities(frozenset({"c2"}))
    assert chunks
    assert all(chunk.visibility is Visibility.COMMUNITY for chunk in chunks)


def test_withdrawing_public_sharing_consent_hides_it_at_once(client, engine):
    add(engine, visibility=Visibility.PUBLIC)
    assert ids(browse(client)) == ["r2"]
    with session_scope(engine) as session:
        ConsentRepository(session).revoke("consent-1")
    assert ids(browse(client)) == []
    assert ids(browse(client, q="water", view="translation")) == []


def test_a_recording_taken_out_of_publication_disappears_even_if_its_index_is_stale(client, engine):
    add(engine, visibility=Visibility.PUBLIC)
    with session_scope(engine) as session:
        RecordingRepository(session).set_status("r2", RecordingStatus.REVIEW)
    assert ids(browse(client)) == []
    assert ids(browse(client, q="water", view="translation")) == []


def test_making_a_recording_private_hides_it_before_the_index_is_rebuilt(client, engine):
    add(engine, visibility=Visibility.PUBLIC)
    with session_scope(engine) as session:
        RecordingRepository(session).set_visibility("r2", Visibility.COMMUNITY)
    with Session(engine) as session:  # the chunks still say public: the gate must not trust them
        chunks = ChunkRepository(session).for_communities(frozenset({"c2"}))
    assert all(chunk.visibility is Visibility.PUBLIC for chunk in chunks)
    assert ids(browse(client)) == []
    assert ids(browse(client, q="water", view="translation")) == []


def test_the_community_still_sees_its_own_recording_after_it_goes_private(client, engine):
    add(engine, visibility=Visibility.PUBLIC)
    with session_scope(engine) as session:
        RecordingRepository(session).set_visibility("r2", Visibility.COMMUNITY)
    act_as(INSIDER)
    assert ids(browse(client)) == ["r2"]


# --- choosing a language and a form ------------------------------------------------------


def test_the_reader_chooses_the_language_and_whether_to_read_the_original_or_the_translation(
    client, engine
):
    add(engine, "r-tamil", visibility=Visibility.PUBLIC)
    add(engine, "r-hindi", visibility=Visibility.PUBLIC, language="hi")
    assert sorted(ids(browse(client))) == ["r-hindi", "r-tamil"]
    assert ids(browse(client, language="ta")) == ["r-tamil"]
    assert ids(browse(client, language="hi")) == ["r-hindi"]
    original = browse(client, language="ta").json()["items"][0]
    assert original["view"] == "original"
    assert "தண்ணீர்" in original["passage"]
    translation = browse(client, language="ta", view="translation").json()["items"][0]
    assert translation["view"] == "translation"
    assert "water" in translation["passage"]


def test_search_finds_words_in_the_original_script(client, engine):
    add(engine, visibility=Visibility.PUBLIC)
    assert ids(browse(client, q="தண்ணீர்")) == ["r2"]


def test_the_reader_can_filter_by_kind(client, engine):
    add(engine, "r-song", visibility=Visibility.PUBLIC, kind=HeritageKind.SONG)
    add(engine, "r-story", visibility=Visibility.PUBLIC, kind=HeritageKind.STORY)
    assert ids(browse(client, kind="song")) == ["r-song"]
    assert ids(browse(client, kind="story")) == ["r-story"]


# --- what must accompany a passage -------------------------------------------------------


def test_a_remedy_always_carries_the_not_medically_validated_notice(client, engine):
    add(engine, "r-remedy", visibility=Visibility.PUBLIC, kind=HeritageKind.REMEDY)
    add(engine, "r-story", visibility=Visibility.PUBLIC)
    items = {i["recording_id"]: i for i in browse(client).json()["items"]}
    assert items["r-remedy"]["notices"] == [REMEDY_NOTICE]
    assert items["r-story"]["notices"] == []
    searched = browse(client, q="water", view="translation").json()["items"]
    remedy = next(i for i in searched if i["recording_id"] == "r-remedy")
    assert remedy["notices"] == [REMEDY_NOTICE]
    assert "not medically validated" in REMEDY_NOTICE.lower()
    assert "traditional notes of elders" in REMEDY_NOTICE.lower()


def test_a_remedy_can_be_public_like_any_other_kind(client, engine):
    add(engine, "r-remedy", visibility=Visibility.PUBLIC, kind=HeritageKind.REMEDY)
    assert ids(browse(client)) == ["r-remedy"]


def test_the_contributing_community_is_named_only_when_the_consent_allows_credit(client, engine):
    add(engine, "r-credit", visibility=Visibility.PUBLIC)
    add(
        engine,
        "r-anon",
        visibility=Visibility.PUBLIC,
        consent_id="c-anon",
        consent={"rights": WITHOUT_CREDIT},
    )
    items = {i["recording_id"]: i for i in browse(client).json()["items"]}
    assert items["r-credit"]["community"] == "c2"
    assert items["r-anon"]["community"] is None


def test_no_response_exposes_the_uploader_or_the_audio_location(client, engine):
    add(engine, visibility=Visibility.PUBLIC)
    body = browse(client).text + browse(client, q="water", view="translation").text
    for secret in ("uploader", "audio_key", "recordings/c2", "consent"):
        assert secret not in body


# --- the endpoint itself -----------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 51},
        {"limit": 0},
        {"q": "x" * 201},
        {"language": "TA"},
        {"kind": "gossip"},
        {"view": "x"},
        {"unknown": "1"},
    ],
    ids=["too-many", "none", "long-query", "bad-language", "bad-kind", "bad-view", "extra"],
)
def test_bad_parameters_are_rejected(client, params):
    assert browse(client, **params).status_code == 422


def test_the_library_needs_a_signed_in_user():
    app.dependency_overrides.clear()
    assert TestClient(app).get("/v1/library").status_code in {401, 503}


def test_a_query_with_no_usable_words_returns_nothing_instead_of_everything(client, engine):
    add(engine, visibility=Visibility.PUBLIC)
    assert ids(browse(client, q="!!! ???")) == []


def test_the_limit_is_respected(client, engine):
    for index in range(5):
        add(engine, f"r{index}", visibility=Visibility.PUBLIC)
    assert len(ids(browse(client, limit=3))) == 3


# --- each protection on its own (the rules overlap, so these isolate them) -----------------


def test_a_recording_made_public_stays_hidden_from_outsiders_until_it_is_indexed_as_public(
    client, engine
):
    add(engine, visibility=Visibility.COMMUNITY)  # indexed while private: its chunks say community
    with session_scope(engine) as session:
        RecordingRepository(session).set_visibility("r2", Visibility.PUBLIC)
    assert ids(browse(client)) == []  # chunks were never marked public
    assert ids(browse(client, q="water", view="translation")) == []
    index_one(IndexDeps(lambda: session_scope(engine)), "r2")  # the queued re-index runs
    assert ids(browse(client)) == ["r2"]


def test_dropping_the_public_sharing_right_from_a_consent_hides_public_chunks_at_once(
    client, engine
):
    add(engine, visibility=Visibility.PUBLIC)
    assert ids(browse(client)) == ["r2"]
    with session_scope(engine) as session:
        row = session.get(ConsentRow, "consent-1")
        row.rights = [r for r in row.rights if r != Right.PUBLIC_SHARING.value]
    assert ids(browse(client)) == []
    assert ids(browse(client, q="water", view="translation")) == []
    act_as(INSIDER)  # the community itself still reads it: only public reading ended
    assert ids(browse(client)) == ["r2"]
