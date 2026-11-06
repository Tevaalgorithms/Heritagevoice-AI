"""A credit (who to thank, who told it, a book or website) is shown only while consent allows it."""

import pytest
from sqlalchemy import create_engine

from app.credits import OriginLookup, credit_for
from app.db.session import session_scope
from app.db.tables import Base
from app.indexing import IndexDeps, index_one
from app.library import browse
from app.models.credit import MAX_NAME, MAX_NOTE, Credit, SourceKind, clean_text
from app.models.library import LibraryFilter
from app.models.records import Right
from tests.helpers import consent, person
from tests.index_helpers import published

CREDITED = {
    "credit_name": "Amma Selvi",
    "source_kind": SourceKind.FAMILY,
    "source_note": "My grandmother, in Jaffna",
}
ALL = tuple(Right)
NO_CREDIT = tuple(r for r in Right if r is not Right.ATTRIBUTION)


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'credits.db'}")
    Base.metadata.create_all(engine)
    return engine


def seed(engine, rights, **extra):
    with session_scope(engine) as session:
        return published(
            session, visibility="public", consent={"rights": rights}, **CREDITED, **extra
        )


def test_a_credit_is_shown_when_the_consent_allows_attribution(engine):
    recording = seed(engine, ALL)
    credit = credit_for(recording, consent(rights=ALL))
    assert credit == Credit(
        name="Amma Selvi", source_kind=SourceKind.FAMILY, source_note="My grandmother, in Jaffna"
    )


@pytest.mark.parametrize(
    "the_consent",
    [consent(rights=NO_CREDIT), consent(rights=ALL, revoked=True), None],
    ids=["no attribution right", "withdrawn", "no consent"],
)
def test_without_the_attribution_right_the_credit_stays_private(engine, the_consent):
    recording = seed(engine, ALL)
    assert credit_for(recording, the_consent) is None


def test_a_recording_with_no_credit_given_has_none_to_show(engine):
    with session_scope(engine) as session:
        recording = published(session)
    assert credit_for(recording, consent(rights=ALL)) is None


def test_text_is_cleaned_to_one_plain_line_within_its_limit():
    assert clean_text("  Amma \n\t Selvi  ", MAX_NAME) == "Amma Selvi"
    assert clean_text("a\x00b\x1fc", MAX_NAME) == "a b c"
    assert clean_text("x" * 500, MAX_NOTE) == "x" * MAX_NOTE
    assert clean_text("   ", MAX_NAME) is None
    assert clean_text(None, MAX_NAME) is None


def test_the_origin_lookup_gives_the_date_always_and_the_credit_only_if_allowed(engine):
    seed(engine, ALL)
    with session_scope(engine) as session:
        published(session, "r2", consent_id="c-none", consent={"rights": NO_CREDIT}, **CREDITED)
    found = OriginLookup(lambda: session_scope(engine))(["r1", "r2", "gone"])
    assert set(found) == {"r1", "r2"}
    assert found["r1"].credit.name == "Amma Selvi"
    assert found["r2"].credit is None
    assert found["r1"].added == found["r2"].added != ""
    assert (found["r1"].heritage_kind, found["r1"].language) == ("story", "ta")


def test_a_library_entry_carries_the_credit_only_with_the_attribution_right(engine):
    seed(engine, ALL)
    with session_scope(engine) as session:
        published(session, "r2", consent_id="c-none", consent={"rights": NO_CREDIT}, **CREDITED)
    for recording_id in ("r1", "r2"):
        index_one(IndexDeps(lambda: session_scope(engine)), recording_id)
    with session_scope(engine) as session:
        entries = {e.recording_id: e for e in browse(session, person(), LibraryFilter())}
    assert entries["r1"].credit.name == "Amma Selvi"
    assert entries["r2"].credit is None
    assert entries["r2"].added
