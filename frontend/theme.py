"""Look and feel: the colours and mood of the README banner (a sunset story circle that turns
into a web of preserved knowledge). Static markup only; nothing a user typed is ever inserted."""

from pathlib import Path

import streamlit as st

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
    "Every elder's story is a library. "
    "We help communities keep their voices, languages and memory alive."
)


def apply() -> None:
    st.markdown(f"<style>{STYLESHEET.read_text()}</style>", unsafe_allow_html=True)


def _cards() -> str:
    cards = "".join(f"<div class='hv-card'><b>{t}</b><p>{d}</p></div>" for t, d in VALUES)
    return f"<div class='hv-cards'>{cards}</div>"


def landing() -> None:
    """Hero shown above the sign-in button."""
    st.image(str(BANNER), use_container_width=True)
    st.markdown(
        "<div class='hv-lead' style='text-align:center;margin:.4rem auto 1.6rem;max-width:760px'>"
        f"{LEAD}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(_cards(), unsafe_allow_html=True)


def brand() -> None:
    st.sidebar.markdown(
        "<div class='hv-brand'>Heritage<span>Voice</span> AI</div>"
        "<div class='hv-tag'>Living heritage, in their own words</div>",
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str) -> None:
    st.header(title)
    st.markdown(f"<p class='hv-sub'>{subtitle}</p>", unsafe_allow_html=True)


def footer() -> None:
    st.markdown(
        "<p class='hv-foot'>Preserving human heritage, with consent and with care.</p>",
        unsafe_allow_html=True,
    )
