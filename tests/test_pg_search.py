"""Tests that need a real PostgreSQL (keyword search, Tamil tokenization, the migration).

Set HERITAGEVOICE_TEST_DATABASE_URL to a database whose name ends in `_test`; the tests drop and
recreate its schema. They are skipped otherwise. CI provides one.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.repositories import ChunkRepository
from app.db.session import session_scope
from app.indexing import IndexDeps, index_one
from app.models.transcript import Segment
from app.retrieval.lexical import lexical_search
from app.retrieval.search import lexical_evidence
from tests.helpers import person
from tests.index_helpers import published

URL = os.environ.get("HERITAGEVOICE_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not URL, reason="HERITAGEVOICE_TEST_DATABASE_URL is not set")


@pytest.fixture
def engine(monkeypatch):
    assert URL is not None
    database = make_url(URL).database or ""
    if not database.endswith("_test"):
        pytest.fail(f"Refusing to reset database {database!r}: its name must end in _test")
    engine = create_engine(URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    monkeypatch.setenv("HERITAGEVOICE_DATABASE_URL", URL)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


def index_published(engine, recording_id="r1", community="c1", **content):
    with Session(engine) as session:
        published(session, recording_id, community, **content)
        session.commit()
    index_one(IndexDeps(lambda: session_scope(engine)), recording_id)


def ids(engine, query, communities=("c1",)):
    with Session(engine) as session:
        return lexical_search(session, query, frozenset(communities))


def test_the_migration_creates_the_full_text_index(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            text("select indexdef from pg_indexes where indexname = 'ix_evidence_chunk_fts'")
        ).all()
    assert len(rows) == 1
    assert "to_tsvector('simple'" in rows[0][0]


def test_the_database_keeps_tamil_words_whole(engine):
    """If this fails the database locale is wrong (for example C): keyword search would break."""
    with engine.connect() as connection:
        lexemes = connection.execute(
            text("select tsvector_to_array(to_tsvector('simple', 'வணக்கம் ஏற்றம்'))")
        ).scalar()
    assert sorted(lexemes) == sorted(["வணக்கம்", "ஏற்றம்"])


def test_exact_tamil_and_english_terms_are_found(engine):
    index_published(engine)
    assert len(ids(engine, "ஏற்றம்")) == 1
    assert len(ids(engine, "lever")) == 1


def test_a_part_of_a_word_does_not_match_a_whole_word(engine):
    index_published(engine)
    assert ids(engine, "ஏற்") == []
    assert ids(engine, "lev") == []


def test_a_question_matches_chunks_sharing_any_word_best_first(engine):
    index_published(engine)
    ranked = ids(engine, "How did villagers share water when rain was scarce")
    assert ranked == ["r1:translation:v1:c0"]


def test_more_shared_words_rank_higher(engine):
    first = [Segment(segment_id="s1", start_s=0.0, end_s=1.0, text="water well water well")]
    second = [Segment(segment_id="s1", start_s=0.0, end_s=1.0, text="water songs harvest")]
    index_published(engine, "r1", transcript=first, translation=None)
    index_published(engine, "r2", transcript=second, translation=None)
    assert ids(engine, "water well") == ["r1:transcript:v1:c0", "r2:transcript:v1:c0"]


def test_only_the_callers_communities_are_searched(engine):
    index_published(engine, "r1", "c1")
    index_published(engine, "r2", "c2")
    assert {i.split(":")[0] for i in ids(engine, "ஏற்றம்", ("c1",))} == {"r1"}
    assert {i.split(":")[0] for i in ids(engine, "ஏற்றம்", ("c1", "c2"))} == {"r1", "r2"}
    assert ids(engine, "ஏற்றம்", ("c3",)) == []


@pytest.mark.parametrize(
    "hostile",
    ["'; DROP TABLE evidence_chunk; --", "a | b & !c", "water:* <-> well", '"', "\\", "()"],
)
def test_hostile_query_text_is_safe(engine, hostile):
    index_published(engine)
    ids(engine, hostile)  # must not raise
    with Session(engine) as session:
        assert len(ChunkRepository(session).ids_for_recording("r1")) == 2


def test_the_authorized_search_returns_evidence_from_postgres(engine):
    index_published(engine)
    with Session(engine) as session:
        (found,) = lexical_evidence(session, person(communities=("c1",)), "ஏற்றம்")
        assert found.document_id == "r1"
        assert found.retrieval_methods == {"bm25"}
        assert lexical_evidence(session, person(communities=("c2",)), "ஏற்றம்") == []


# --- public visibility on the real full-text path ------------------------------------------


def test_public_chunks_are_found_by_outsiders_and_by_users_with_no_community(engine):
    from app.models.records import Visibility  # noqa: PLC0415

    index_published(engine, "r-pub", "c2", visibility=Visibility.PUBLIC)
    index_published(
        engine, "r-priv", "c3", consent_id="consent-c3", visibility=Visibility.COMMUNITY
    )
    assert any("r-pub" in found for found in ids(engine, "தண்ணீர்", ("c1",)))
    assert any("r-pub" in found for found in ids(engine, "தண்ணீர்", ()))  # no community at all
    assert not any("r-priv" in found for found in ids(engine, "தண்ணீர்", ("c1",)))
    assert not any("r-priv" in found for found in ids(engine, "தண்ணீர்", ()))
    assert any("r-priv" in found for found in ids(engine, "தண்ணீர்", ("c3",)))  # its own community


def test_the_eligibility_gate_on_postgres_hides_public_chunks_once_consent_is_revoked(engine):
    from app.db.repositories import ConsentRepository  # noqa: PLC0415
    from app.models.records import Visibility  # noqa: PLC0415

    index_published(engine, "r-pub", "c2", visibility=Visibility.PUBLIC)
    outsider = person(communities=("c1",))
    with Session(engine) as session:
        assert [e.document_id for e in lexical_evidence(session, outsider, "தண்ணீர்")] == ["r-pub"]
    with session_scope(engine) as session:
        ConsentRepository(session).revoke("consent-1")
    with Session(engine) as session:
        assert lexical_evidence(session, outsider, "தண்ணீர்") == []
