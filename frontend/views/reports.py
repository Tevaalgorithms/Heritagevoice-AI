"""Reports (admins): decide what to do with recordings people reported.

Taking a recording down withdraws it at once (search, playback and the knowledge graph stop);
keeping it closes the report. Either way every open report about that recording is closed. The
reporter is shown here only, never to the person who shared the recording.
"""

import streamlit as st

from frontend import theme
from frontend.api_client import ApiClient, ApiError, ReportView
from frontend.kinds import label_for
from frontend.messages import message_for
from frontend.views.report import REASONS


def _decide(client: ApiClient, report: ReportView, take_down: bool) -> None:
    try:
        client.decide_report(report.id, take_down)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.rerun()


def _card(client: ApiClient, report: ReportView) -> None:
    with theme.card(f"report-{report.id}"):
        reason = REASONS.get(report.reason, report.reason)
        st.markdown(f"**{reason}**")
        st.caption(
            f"{label_for(report.heritage_kind)} · {report.language} · "
            f"shared by {report.community} · reported by {report.reporter} · "
            f"{report.reports_for_recording} report(s) in all"
        )
        if report.note:
            st.markdown(theme.passage_html(report.note), unsafe_allow_html=True)
        if report.opening:
            st.caption("How the recording begins:")
            st.markdown(theme.passage_html(report.opening), unsafe_allow_html=True)
        down, keep, _ = st.columns([1, 1, 3])
        if down.button("Take it down", type="primary", key=f"down-{report.id}"):
            _decide(client, report, True)
        if keep.button("Keep it", key=f"keep-{report.id}"):
            _decide(client, report, False)


def render(client: ApiClient) -> None:
    """The Reports page."""
    theme.page_header(
        "Reports",
        "Recordings people said should not be shared. Taking one down withdraws it at once.",
        "review",
    )
    try:
        reports = client.reports()
    except ApiError as error:
        st.error(message_for(error))
        return
    if not reports:
        st.info("No reports are waiting.")
        return
    st.caption(f"{len(reports)} waiting, oldest first")
    for report in reports:
        _card(client, report)
