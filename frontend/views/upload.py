"""Upload page: send a recording, follow its processing, then read the draft transcript.

Editing the transcript and seeking the audio from a segment arrive with segments 04 and 10.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import streamlit as st

from app.languages import LANGUAGES as ALL_LANGUAGES
from app.models.groups import OPEN_COMMUNITY
from frontend import theme
from frontend.api_client import ApiClient, ApiError, MyGroupView, RecordingView, UploadSpec
from frontend.format import failure_message, progress_for, segment_rows
from frontend.kinds import BY_KEY, KINDS, REMEDY_NOTICE
from frontend.messages import message_for
from frontend.rights import describe
from frontend.upload_input import idempotency_key, pick_audio

AUDIO_TYPES = ["wav", "mp3", "flac", "ogg", "m4a", "mp4"]
LANGUAGES = {f"{lang.name} · {lang.native_name}": lang.code for lang in ALL_LANGUAGES}
POLL_SECONDS = 2.0
MAX_POLLS = 150
DONE = {"review", "published", "failed"}


def follow_job(client: ApiClient, job_id: str) -> str | None:
    """Show progress until the job finishes; return its error code, if it failed."""
    bar, label = st.progress(0.0), st.empty()
    for _ in range(MAX_POLLS):
        job = client.get_job(job_id)
        fraction, text = progress_for(job.status, job.stage)
        bar.progress(fraction)
        label.write(text)
        if job.status in DONE:
            return job.error if job.status == "failed" else None
        time.sleep(POLL_SECONDS)
    label.write("Still processing. Check back soon.")
    return None


def show_transcript(recording: RecordingView) -> None:
    if recording.transcript is None:
        st.info("No transcript yet.")
        return
    st.subheader(f"Draft transcript (version {recording.transcript.version})")
    st.caption("This draft is not searchable until a reviewer approves it.")
    st.dataframe(segment_rows(recording.transcript.segments), hide_index=True)


def submit(client: ApiClient, spec: UploadSpec) -> None:
    """Send the audio, follow its processing, then show the draft transcript."""
    try:
        with st.spinner("Uploading…"):
            result = client.upload_recording(spec, idempotency_key(spec.data))
        error = follow_job(client, result.job_id)
        if error:
            st.error(failure_message(error))
            return
        show_transcript(client.get_recording(result.recording_id))
    except ApiError as error:
        st.error(message_for(error))


def _choose_kind() -> str:
    key = st.selectbox(
        "What is this recording?",
        [kind.key for kind in KINDS],
        format_func=lambda k: f"{BY_KEY[k].icon} {BY_KEY[k].label}",
        help="Songs, lessons, practices and remedies are welcome as well as stories.",
    )
    if key == "remedy":
        st.info(REMEDY_NOTICE)
    return str(key)


def _record_or_upload() -> bytes | None:
    """Record in the browser, or upload an existing file. Both end up as the same audio bytes."""
    record_tab, file_tab = st.tabs(
        [":material/mic: Record now", ":material/upload_file: Upload a file"]
    )
    with record_tab:
        st.caption(
            "Press the microphone, speak in your own language, then press stop. Play it back."
        )
        recorded = st.audio_input("Record", label_visibility="collapsed", key="hv-recording")
    with file_tab:
        file = st.file_uploader("Audio or video file", type=AUDIO_TYPES)
        st.caption("Video must be MP4. Its sound is transcribed; the picture is not used yet.")
    return pick_audio(recorded, file)


VISIBILITY_CHOICES = {
    "Only my group": "community",
    "All signed-in users (needs your group's public-sharing consent)": "public",
}
REMEDY_PUBLIC_NOTICE = "Not medically validated. Shared from the traditional notes of elders."
PUBLIC_NOTE = (
    "An admin reviews everything before it is shared. Public sharing also needs a consent record "
    "that includes public sharing, or the upload is refused."
)


def _choose_visibility(kind: str) -> str:
    label = st.radio(
        "Who may read this once it is approved?",
        list(VISIBILITY_CHOICES),
        help="You can start with your community and widen it later; an admin makes the change.",
    )
    visibility = VISIBILITY_CHOICES[str(label)]
    if visibility == "public":
        st.caption(PUBLIC_NOTE)
        if kind == "remedy":
            st.info(f"Readers will see: {REMEDY_PUBLIC_NOTICE}")
    return visibility


def _choose_language() -> str:
    label = st.selectbox(
        "Language spoken",
        list(LANGUAGES),
        help="Speak in your own language. If yours is missing, ask an admin to add it.",
    )
    return LANGUAGES[label]


def _my_groups(client: ApiClient) -> list[MyGroupView]:
    try:
        return client.my_groups()
    except ApiError as error:
        st.error(message_for(error))
        return []


def _choose_group(client: ApiClient) -> tuple[str, str] | None:
    """Pick one of your groups and a consent it has recorded. None if there is nothing to pick."""
    groups = _my_groups(client)
    if not groups:
        st.warning("You are not in a group yet. Ask an administrator or coordinator to add you.")
        return None
    group = st.selectbox(
        "Group",
        groups,
        format_func=lambda g: g.name,
        help="The family or community this recording belongs to.",
    )
    if not group.consents:
        st.warning(
            f"“{group.name}” has no consent recorded yet. Ask a coordinator or administrator "
            "to record what the group allows (Groups and consent), then come back."
        )
        return None
    consent = st.selectbox(
        "What the group allows",
        group.consents,
        format_func=lambda c: f"{describe(c.rights)} (v{c.policy_version}, {c.id[:16]})",
        help="The consent the group agreed to. It decides what may be done with the recording.",
    )
    return group.id, consent.id


OPEN = "Everyone (open sharing)"
GROUP = "Only my family or group"
OPEN_TERMS = (
    "Sharing openly means anyone who searches can find this recording once an administrator has "
    "approved it. AI will write it down (transcribe), translate it, and use it to answer questions."
)


@dataclass(frozen=True)
class Destination:
    """Where the recording goes. `consent` gives the consent reference when the upload is sent."""

    community_id: str
    visibility: str
    consent: Callable[[], str]


def _open_destination(client: ApiClient) -> Destination | None:
    """Open sharing: no group. The contributor gives the consent here, on the form."""
    st.info(OPEN_TERMS)
    playback = st.checkbox("People may listen to the recording, not only read it", value=True)
    credit = st.checkbox("Credit the speaker by name when it is shown", value=False)
    sure = st.checkbox("I have the right to share this recording, and I agree to the above.")
    if not sure:
        return None
    return Destination(OPEN_COMMUNITY, "public", lambda: client.give_open_consent(playback, credit))


def _group_destination(client: ApiClient, kind: str) -> Destination | None:
    visibility = _choose_visibility(kind)
    chosen = _choose_group(client)
    if chosen is None:
        return None
    community, consent = chosen
    return Destination(community, visibility, lambda: consent)


def _choose_destination(client: ApiClient, kind: str) -> Destination | None:
    audience = st.radio(
        "Who is this for?",
        [OPEN, GROUP],
        help="Open sharing needs no group. A family or group keeps it to the people in it.",
    )
    if audience == OPEN:
        return _open_destination(client)
    return _group_destination(client, kind)


def _send(client: ApiClient, spec: UploadSpec, destination: Destination) -> None:
    try:
        consent_id = destination.consent()
    except ApiError as error:
        st.error(message_for(error))
        return
    submit(
        client,
        spec.model_copy(
            update={
                "community_id": destination.community_id,
                "consent_id": consent_id,
                "visibility": destination.visibility,
            }
        ),
    )


def render(client: ApiClient) -> None:
    """The Upload page: record or upload audio, say what it is, and send it for review."""
    theme.page_header(
        "Add a recording",
        "Record a song, story, lesson or practice in your own language, or upload a file. "
        "It is transcribed, then reviewed by people before anyone can search it.",
        "upload",
    )
    audio = _record_or_upload()
    kind = _choose_kind()
    language = _choose_language()
    destination = _choose_destination(client, kind)
    if st.button("Send for review", disabled=not (audio and destination)) and destination:
        spec = UploadSpec(
            data=audio or b"",
            language=language,
            community_id="",
            consent_id="",
            heritage_kind=kind,
        )
        _send(client, spec, destination)
