"""Review page: compare transcript and translation, edit, approve or reject, then publish."""

import streamlit as st

from frontend import theme
from frontend.api_client import (
    ApiClient,
    ApiError,
    RecordingSummary,
    RecordingView,
    ReviewSpec,
    VersionView,
)
from frontend.credit import long_date, origin_line
from frontend.format import changed_edits, editor_rows
from frontend.kinds import label_for
from frontend.messages import message_for
from frontend.views.playback import listen_button

REVIEWABLE = {"review", "published"}
WITHDRAW_WARNING = (
    "Withdrawing takes this recording out of the Library, search, answers and the knowledge graph "
    "at once, and stops playback. The record and the reason stay in the audit trail. "
    "This cannot be undone."
)


def _label(recording: RecordingSummary) -> str:
    kind = label_for(recording.heritage_kind)
    return f"{kind} · {recording.id[:8]} · {recording.language} · {recording.status}"


def _act(action: object, success: str) -> None:
    """Run a client call, show the result, and reload on success."""
    try:
        action()  # type: ignore[operator]
    except ApiError as error:
        st.error(message_for(error))
        return
    st.success(success)
    st.rerun()


def _version_panel(client: ApiClient, recording: RecordingView, kind: str) -> None:
    version: VersionView | None = getattr(recording, kind)
    st.subheader(kind.capitalize())
    if version is None:
        st.info(f"No {kind} yet.")
        return
    st.caption(f"Version {version.version} · {version.status}")
    key = f"{recording.id}-{kind}-{version.version}"
    rows = st.data_editor(
        editor_rows(version.segments),
        key=key,
        hide_index=True,
        disabled=["id", "time"],
    )
    edits = changed_edits(version.segments, list(rows))
    save, approve, reject = st.columns(3)
    if save.button("Save as new draft", key=f"{key}-save", disabled=not edits):
        _act(lambda: client.edit_draft(recording.id, kind, version.version, edits), "Saved.")
    decision = ReviewSpec(kind=kind, expected_version=version.version, approved=True)
    if approve.button("Approve", key=f"{key}-ok", disabled=version.status != "draft"):
        _act(lambda: client.review(recording.id, decision), "Approved.")
    rejection = decision.model_copy(update={"approved": False})
    if reject.button("Reject", key=f"{key}-no", disabled=version.status != "draft"):
        _act(lambda: client.review(recording.id, rejection), "Rejected.")


VISIBILITIES = {"Only the community": "community", "All signed-in users": "public"}


def _visibility_panel(client: ApiClient, recording: RecordingView) -> None:
    """Who may read this once it is published. Going public needs the public-sharing consent."""
    st.subheader("Who may read it")
    labels = list(VISIBILITIES)
    current = next(i for i, v in enumerate(VISIBILITIES.values()) if v == recording.visibility)
    choice = st.radio("Visibility", labels, current, key=f"{recording.id}-visibility")
    if st.button("Save visibility", disabled=VISIBILITIES[str(choice)] == recording.visibility):
        _act(lambda: client.set_visibility(recording.id, VISIBILITIES[str(choice)]), "Saved.")


def _review_recording(client: ApiClient, recording_id: str) -> None:
    try:
        recording = client.get_recording(recording_id)
    except ApiError as error:
        st.error(message_for(error))
        return
    listen_button(client.recording_media, recording.id, f"{recording.id}-listen")
    left, right = st.columns(2)
    with left:
        _version_panel(client, recording, "transcript")
    with right:
        _version_panel(client, recording, "translation")
    if st.button("Publish approved transcript", disabled=recording.status != "review"):
        _act(lambda: client.publish(recording.id), "Published.")
    _visibility_panel(client, recording)
    _credit_panel(recording)
    _withdraw_panel(client, recording)


def _credit_panel(recording: RecordingView) -> None:
    """What the contributor entered about who to thank and where it came from, and whether readers
    will see it. Checked here before the recording is published."""
    credit = recording.credit
    if credit is None:
        st.caption(f"No credit or source was given. Added {long_date(recording.added)}.")
        return
    entered = origin_line(recording.added, credit.name, credit.source_kind, credit.source_note)
    st.markdown("**Credit and source**")
    st.caption(entered)
    st.caption(
        "Readers will see this."
        if recording.credit_public
        else "Readers will not see this: the consent does not include crediting."
    )


def can_withdraw(reason: str, understood: bool) -> bool:
    """Withdrawing needs a reason and an explicit confirmation."""
    return bool(reason.strip()) and understood


def _withdraw_panel(client: ApiClient, recording: RecordingView) -> None:
    """Take the recording down. Kept inside an expander so it is never one stray click away."""
    with st.expander("Withdraw this recording"):
        st.warning(WITHDRAW_WARNING)
        reason = st.text_input(
            "Why is it being withdrawn?", max_chars=150, key=f"withdraw-reason-{recording.id}"
        )
        understood = st.checkbox("I understand this cannot be undone.", key=f"sure-{recording.id}")
        if st.button(
            "Withdraw now",
            type="primary",
            disabled=not can_withdraw(reason, understood),
            key=f"withdraw-{recording.id}",
        ):
            _act(
                lambda: client.withdraw_recording(recording.id, reason.strip()),
                "Withdrawn. It is no longer shared.",
            )


def _load_recordings(client: ApiClient) -> list[RecordingSummary] | None:
    try:
        return [r for r in client.list_recordings() if r.status in REVIEWABLE]
    except ApiError as error:
        st.error(message_for(error))
        return None


def render(client: ApiClient) -> None:
    theme.page_header(
        "Review",
        "Check each transcript and translation. Only approved work becomes part of the collection.",
        "review",
    )
    recordings = _load_recordings(client)
    if not recordings:
        if recordings is not None:
            st.info("Nothing is waiting for review.")
        return
    chosen = st.selectbox("Recording", recordings, format_func=_label)
    if chosen is not None:
        _review_recording(client, chosen.id)
