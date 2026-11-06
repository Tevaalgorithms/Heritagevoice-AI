"""Graph assertions: relationships proposed from a recording and what a person decided about them.

PostgreSQL is the source of truth. Neo4j only ever receives the approved ones (see
`app.graph_projection`), so a pending or rejected assertion can never be found by a question.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.tables import GraphAssertionRow
from app.models.records import GraphAssertion, Relation, ReviewState


def _to_assertion(row: GraphAssertionRow) -> GraphAssertion:
    return GraphAssertion(
        id=row.id,
        recording_id=row.recording_id,
        subject=row.subject,
        relation=Relation(row.relation),
        object=row.object,
        subject_en=row.subject_en,
        object_en=row.object_en,
        asserted_by=row.asserted_by,
        review_state=ReviewState(row.review_state),
        supporting_segment_id=row.supporting_segment_id,
        transcript_version=row.transcript_version,
        confidence=row.confidence,
        policy_ref=row.policy_ref,
    )


def _escape(text: str) -> str:
    """Make `%`, `_` and the escape character itself match literally in a LIKE pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class GraphAssertionRepository:
    """Stores assertions and their review state."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_many(self, assertions: list[GraphAssertion]) -> None:
        for assertion in assertions:
            self._session.add(GraphAssertionRow(**assertion.model_dump(mode="json")))
        self._session.flush()

    def approved_matching(self, text: str, limit: int) -> list[GraphAssertion]:
        """Approved assertions that name `text` on either side, in the speaker's words or in their
        English meaning (any, newest first, if empty)."""
        query = select(GraphAssertionRow).where(
            GraphAssertionRow.review_state == ReviewState.APPROVED.value
        )
        if text.strip():
            pattern = f"%{_escape(text.strip().casefold())}%"
            query = query.where(
                func.lower(GraphAssertionRow.subject).like(pattern, escape="\\")
                | func.lower(GraphAssertionRow.object).like(pattern, escape="\\")
                | func.lower(GraphAssertionRow.subject_en).like(pattern, escape="\\")
                | func.lower(GraphAssertionRow.object_en).like(pattern, escape="\\")
            )
        query = query.order_by(GraphAssertionRow.id).limit(limit)
        return [_to_assertion(row) for row in self._session.scalars(query)]

    def get(self, assertion_id: str) -> GraphAssertion | None:
        row = self._session.get(GraphAssertionRow, assertion_id)
        return None if row is None else _to_assertion(row)

    def replace_pending(
        self, recording_id: str, version: int, proposed: list[GraphAssertion]
    ) -> int:
        """Drop pending proposals about older transcripts, then add the ones not seen before.

        Approved and rejected assertions are never touched, so a decision survives a re-run.
        """
        self._session.execute(
            delete(GraphAssertionRow).where(
                GraphAssertionRow.recording_id == recording_id,
                GraphAssertionRow.review_state == ReviewState.PENDING.value,
                GraphAssertionRow.transcript_version != version,
            )
        )
        known = set(
            self._session.scalars(
                select(GraphAssertionRow.id).where(GraphAssertionRow.recording_id == recording_id)
            )
        )
        fresh = [a for a in proposed if a.id not in known]
        self.add_many(fresh)
        return len(fresh)

    def get_many(self, assertion_ids: list[str]) -> dict[str, GraphAssertion]:
        if not assertion_ids:
            return {}
        query = select(GraphAssertionRow).where(GraphAssertionRow.id.in_(assertion_ids))
        return {row.id: _to_assertion(row) for row in self._session.scalars(query)}

    def approved_for(self, recording_id: str) -> list[GraphAssertion]:
        query = (
            select(GraphAssertionRow)
            .where(
                GraphAssertionRow.recording_id == recording_id,
                GraphAssertionRow.review_state == ReviewState.APPROVED.value,
            )
            .order_by(GraphAssertionRow.id)
        )
        return [_to_assertion(row) for row in self._session.scalars(query)]

    def with_state(self, state: ReviewState, limit: int = 200) -> list[GraphAssertion]:
        query = (
            select(GraphAssertionRow)
            .where(GraphAssertionRow.review_state == state.value)
            .order_by(GraphAssertionRow.id)
            .limit(limit)
        )
        return [_to_assertion(row) for row in self._session.scalars(query)]

    def decide(self, assertion_id: str, state: ReviewState) -> bool:
        """Set the review state. False if the assertion does not exist."""
        row = self._session.get(GraphAssertionRow, assertion_id)
        if row is None:
            return False
        row.review_state = state.value
        self._session.flush()
        return True

    def revise(self, corrected: GraphAssertion) -> bool:
        """Correct the words of an assertion in place (its ID stays, so a re-run adds no copy)."""
        row = self._session.get(GraphAssertionRow, corrected.id)
        if row is None:
            return False
        row.subject, row.relation, row.object = (
            corrected.subject,
            corrected.relation.value,
            corrected.object,
        )
        row.subject_en, row.object_en = corrected.subject_en, corrected.object_en
        self._session.flush()
        return True

    def recording_ids_with_approved(self) -> list[str]:
        query = (
            select(GraphAssertionRow.recording_id)
            .where(GraphAssertionRow.review_state == ReviewState.APPROVED.value)
            .distinct()
        )
        return sorted(self._session.scalars(query))

    def delete_for_recording(self, recording_id: str) -> int:
        result = self._session.execute(
            delete(GraphAssertionRow).where(GraphAssertionRow.recording_id == recording_id)
        )
        self._session.flush()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
