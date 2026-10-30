"""Look and feel: the colours and mood of the README banner (a sunset story circle that turns
into a web of preserved knowledge). Static markup only; nothing a user typed is ever inserted."""

from html import escape
from pathlib import Path

import streamlit as st

from frontend.kinds import KINDS

BANNER = Path(__file__).parent / "static" / "banner.jpg"

STYLESHEET = Path(__file__).parent / "static" / "theme.css"


VALUES = (
    (
        "Community-controlled",
        "Recordings are shared only with the consent of the people who gave them.",
    ),
    ("Grounded in sources", "Answers point back to the voices and documents they come from."),
    (
        "Reviewed by people",
        "Transcripts and translations are checked by humans before they are trusted.",
    ),
)
LEAD = (
    "Every elder's voice is a library. We help communities keep their songs, stories, "
    "lessons and living knowledge alive."
)
LANGUAGES_TITLE = "Speak in your own language"
LANGUAGES_TEXT = (
    "Tell it the way it was told. We keep the original voice and words, and add a translation "
    "for those who need it. We are adding more languages with every community we work with."
)
CLOSING = (
    "What is remembered is never lost. The old songs, the farmer's wisdom and the lessons of "
    "our elders, kept in their own voices for the generations still to come."
)
PROMISE = "Preserving human heritage, with consent and with care."
ICONS = {
    "upload": "<path d='M12 3v12'/><path d='M8 7l4-4 4 4'/><path d='M5 15v4h14v-4'/>",
    "review": "<path d='M5 12l4 4 10-10'/><path d='M4 4h16v16H4z'/>",
    "ask": "<path d='M4 5h16v11H9l-5 4z'/><path d='M8 9h8M8 12h5'/>",
    "settings": (
        "<path d='M4 7h10M18 7h2M4 17h2M10 17h10'/>"
        "<circle cx='16' cy='7' r='2'/><circle cx='8' cy='17' r='2'/>"
    ),
}


def apply() -> None:
    st.markdown(f"<style>{STYLESHEET.read_text()}</style>", unsafe_allow_html=True)


def _cards() -> str:
    cards = "".join(f"<div class='hv-card'><b>{t}</b><p>{d}</p></div>" for t, d in VALUES)
    return f"<div class='hv-cards'>{cards}</div>"


def _kind_chips() -> str:
    chips = "".join(
        f"<span class='hv-chip' title='{escape(k.hint)}'>{k.icon} {escape(k.label)}</span>"
        for k in KINDS
    )
    return f"<div class='hv-chips'><div class='hv-chips-title'>What we preserve</div>{chips}</div>"


def _languages() -> str:
    return (
        "<div class='hv-langs' style='text-align:center'>"
        f"<div class='hv-langs-title'>{LANGUAGES_TITLE}</div>"
        f"<p class='hv-langs-text'>{LANGUAGES_TEXT}</p></div>"
    )


def landing() -> None:
    """Hero shown above the sign-in button."""
    st.image(str(BANNER), use_container_width=True)
    st.markdown(
        "<div class='hv-lead' style='text-align:center;margin:.4rem auto 1.6rem;max-width:760px'>"
        f"{LEAD}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(_cards(), unsafe_allow_html=True)
    st.markdown(_kind_chips(), unsafe_allow_html=True)
    st.markdown(_languages(), unsafe_allow_html=True)


def brand() -> None:
    st.sidebar.markdown(
        "<div class='hv-brand'>Heritage<span>Voice</span> AI</div>"
        "<div class='hv-tag'>Living heritage, in their own words</div>",
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str, icon: str = "ask") -> None:
    st.markdown(
        "<div class='hv-pageicon'><svg viewBox='0 0 24 24' width='26' height='26' fill='none' "
        "stroke='#FFF7E6' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>"
        f"{ICONS[icon]}</svg></div>",
        unsafe_allow_html=True,
    )
    st.header(title)
    st.markdown(f"<p class='hv-sub'>{subtitle}</p>", unsafe_allow_html=True)


def footer() -> None:
    """A closing thought, then the promise the project makes."""
    st.markdown(
        "<div class='hv-closing' style='text-align:center'>"
        f"<div class='hv-closing-line'>{CLOSING}</div>"
        f"<div class='hv-promise'>{PROMISE}</div></div>",
        unsafe_allow_html=True,
    )
