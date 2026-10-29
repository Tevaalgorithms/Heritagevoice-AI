import pytest
from sqlalchemy.orm import Session

from app.bootstrap import create_first_admin
from app.db.engine import make_engine
from app.db.repositories import UserRepository
from app.db.tables import Base
from app.security.roles import Role


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_the_first_admin_is_created_once(engine):
    assert create_first_admin(engine, "sub-1") is True
    assert create_first_admin(engine, "sub-1") is False
    with Session(engine) as session:
        assert UserRepository(session).get("sub-1").role == Role.ADMIN


def test_an_existing_user_is_never_promoted(engine):
    with Session(engine) as session:
        UserRepository(session).create("sub-2", Role.MEMBER, frozenset())
        session.commit()
    assert create_first_admin(engine, "sub-2") is False
    with Session(engine) as session:
        assert UserRepository(session).get("sub-2").role == Role.MEMBER


@pytest.mark.parametrize("bad", ["", "has space", "x" * 65, "semi;colon"])
def test_a_malformed_sub_is_rejected(engine, bad):
    with pytest.raises(ValueError, match="sub must be"):
        create_first_admin(engine, bad)
