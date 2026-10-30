"""Upload page: send a recording, follow its processing, then read the draft transcript.

Editing the transcript and seeking the audio from a segment arrive with segments 04 and 10.
"""

import time
from uuid import uuid4

import streamlit as st

from app.languages import LANGUAGES as ALL_LANGUAGES
from frontend import theme
from frontend.api_client import ApiClient, ApiError, RecordingView, UploadSpec
from frontend.format import failure_message, progress_for, segment_rows
from frontend.kinds import BY_KEY, KINDS, REMEDY_NOTICE
from frontend.messages import message_for

AUDIO_TYPES = ["wav", "mp3", "flac", "ogg", "m4a"]
LANGUAGES = {f"{lang.name} · {lang.native_name}": lang.code for lang in ALL_LANGUAGES}
POLL_SECONDS = 2.0
MAX_POLLS = 150
DONE = {"review", "published", "failed"}


def _key() -> str:
    """One idempotency key per file selection, so a double click cannot upload twice."""
    st.session_state.setdefault("upload_key", uuid4().hex)
    return str(st.session_state["upload_key"])


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
    try:
        with st.spinner("Uploading…"):
            result = client.upload_recording(spec, _key())
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


def render(client: ApiClient) -> None:
    theme.page_header(
        "Upload a recording",
        "Share a song, story, lesson or practice. It is transcribed, then reviewed by people "
        "before anyone can search it.",
        "upload",
    )
    file = st.file_uploader("Audio file", type=AUDIO_TYPES)
    kind = _choose_kind()
    language = LANGUAGES[
        st.selectbox(
            "Language spoken",
            list(LANGUAGES),
            help="Speak in your own language. If yours is missing, ask an admin to add it.",
        )
    ]
    community = st.text_input("Community ID")
    consent = st.text_input("Consent reference")
    if st.button("Upload", disabled=not (file and community and consent)):
        submit(
            client,
            UploadSpec(
                data=file.getvalue(),
                language=language,
                community_id=community,
                consent_id=consent,
                heritage_kind=kind,
            ),
        )
