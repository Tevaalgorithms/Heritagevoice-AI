"""The demo library: its text is well formed, it shows up for anyone, and it can be taken away."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.auth import get_session_factory
from app.api.main import app
from app.db.session import session_scope
from app.db.tables import Base
from app.demo_seed import PREFIX, load_corpus, remove, seed
from app.indexing import IndexDeps
from app.languages import BY_CODE


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def deps(engine):
    return IndexDeps(lambda: session_scope(engine))


@pytest.fixture
def visitor(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    yield TestClient(app)
    app.dependency_overrides.clear()


def shown(visitor, **params):
    response = visitor.get("/v1/public/library", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_the_corpus_is_synthetic_and_every_language_is_one_the_product_accepts():
    corpus = load_corpus()
    assert "SYNTHETIC" in corpus["_note"]
    recordings = corpus["recordings"]
    assert len({r["id"] for r in recordings}) == len(recordings)
    assert all(r["id"].startswith(PREFIX) for r in recordings)
    assert {r["language"] for r in recordings} <= set(BY_CODE)
    assert len({r["language"] for r in recordings}) >= 8


def test_every_non_english_segment_has_an_english_translation_and_questions_point_at_real_ones():
    corpus = load_corpus()
    known = set()
    for recording in corpus["recordings"]:
        for segment in recording["segments"]:
            known.add(f"{recording['id']}:{segment['segment_id']}")
            if recording["language"] != "en":
                assert segment["translation"].strip()
    for question in corpus["questions"]:
        assert set(question["expected_sources"]) <= known
        assert question["answerable"] == bool(question["expected_sources"])


def test_seeding_shows_every_language_to_a_visitor_with_no_account(deps, visitor):
    added, present = seed(deps)
    assert len(added) == len(load_corpus()["recordings"])
    assert present == []
    items = shown(visitor, limit=20)
    assert {i["language"] for i in items} >= {"ta", "hi", "te", "ml", "bn", "fr", "es", "pt", "en"}
    assert {i["recording_id"] for i in shown(visitor, language="hi")} == {"demo-hi-lori"}
    english = shown(visitor, language="ta", view="translation")
    assert english
    assert english[0]["passage"].startswith("In the month of Thai")


def test_a_visitor_can_search_demo_words_in_the_speakers_language(deps, visitor):
    seed(deps)
    assert [i["recording_id"] for i in shown(visitor, q="ghost")] == []
    assert "demo-hi-lori" in {i["recording_id"] for i in shown(visitor, q="लोरी")}


def test_seeding_twice_adds_nothing_the_second_time(deps):
    seed(deps)
    added, present = seed(deps)
    assert added == []
    assert len(present) == len(load_corpus()["recordings"])


def test_removing_takes_the_demo_out_of_the_library_and_can_be_repeated(deps, visitor):
    seed(deps)
    assert len(remove(deps)) == len(load_corpus()["recordings"])
    assert shown(visitor, limit=20) == []
    assert shown(visitor, q="लोरी") == []
    assert remove(deps) == []
