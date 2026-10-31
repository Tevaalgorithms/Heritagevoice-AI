"""Reports about recordings. An admin decides each one; the reporter stays private."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.tables import ItemReportRow
from app.models.records import ItemReport, ReportReason, ReportStatus

LIST_LIMIT = 200


def _to_report(row: ItemReportRow) -> ItemReport:
    return ItemReport(
        id=row.id,
        recording_id=row.recording_id,
        reason=ReportReason(row.reason),
        note=row.note,
        reporter=row.reporter,
        status=ReportStatus(row.status),
    )


class ReportRepository:
    """Stores reports and their outcome."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, report: ItemReport) -> None:
        self._session.add(ItemReportRow(**report.model_dump(mode="json")))
        self._session.flush()

    def with_status(self, status: ReportStatus) -> list[ItemReport]:
        query = (
            select(ItemReportRow)
            .where(ItemReportRow.status == status.value)
            .order_by(ItemReportRow.created_at)
            .limit(LIST_LIMIT)
        )
        return [_to_report(row) for row in self._session.scalars(query)]

    def get(self, report_id: str) -> ItemReport | None:
        row = self._session.get(ItemReportRow, report_id)
        return None if row is None else _to_report(row)

    def resolve_for_recording(
        self, recording_id: str, status: ReportStatus, decided_by: str
    ) -> int:
        """Close every open report about this recording with the same decision."""
        result = self._session.execute(
            update(ItemReportRow)
            .where(
                ItemReportRow.recording_id == recording_id,
                ItemReportRow.status == ReportStatus.OPEN.value,
            )
            .values(status=status.value, resolved_by=decided_by)
        )
        self._session.flush()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
