"""Two public pages that say what HeritageVoice is for: how it works, and why it exists.

The text is fixed in the code. Nothing here comes from a user, and nothing claims more than the
service does (see the Privacy Notice for what is kept and for how long).
"""

import streamlit as st

from frontend import theme
from frontend.legal import OrganisationFacts

REPOSITORY = "https://github.com/Tevaalgorithms/Heritagevoice-AI"

CONTRIBUTORS = (
    "**Create an account** with your email and a password. An administrator approves it.",
    "**Join your group,** a family or a community, or choose open sharing, which needs no group.",
    "**Record or upload** in your own language: a song, story, lesson, practice or remedy.",
    "**Say what may be done with it.** Playing it, writing it down, translating it, making it "
    "searchable, sharing it publicly, and crediting the speaker are each allowed separately.",
    "**Add a credit and a source** if you wish: who to thank, and whether it came from a family "
    "elder, a book or a website. Readers see it only if you allow crediting.",
    "**People review it.** An administrator checks the transcript and the translation, and the "
    "recording is published only after that.",
)
READERS = (
    "**Browse and listen** to what communities share openly. No account is needed.",
    "**Ask a question** once you have signed in. The answer comes only from the recordings you "
    "may read, with a citation to the exact moment, and says so when they do not cover it.",
    "**Follow the connections** between people, places, songs and customs, each shown with the "
    "words that say it.",
)
BEHIND = (
    "Speech is written down with Amazon Transcribe, and the text is translated and read by "
    "language models. Audio is never sent to the language models, only text.",
    "Everything the AI drafts waits for a person. Only approved material is searchable.",
    "If a speaker or a community withdraws consent, the recording disappears from the Library, "
    "from search and from answers at once.",
)
WHY = (
    "Every language carries generations of stories, traditions and knowledge. Many are "
    "disappearing as fewer people speak them and younger generations lose the chance to learn "
    "them. When a language goes, we lose more than words: practices, history and ways of "
    "understanding the world.",
    "Smaller communities have few tools to document their heritage, and general AI tools make "
    "two things worse. They guess: a chatbot will invent a traditional remedy or a village "
    "history that no elder ever told. And they ignore ownership: communities need to decide who "
    "may hear a recording, and to change their mind later.",
    "The goal is not to replace native speakers or cultural experts. It is to give communities "
    "better tools to preserve and share their own heritage.",
)
WE_DO_NOT = (
    "We use no advertising or analytics trackers, and we do not sell personal information.",
    "We do not present a traditional remedy as medical advice. Every remedy carries the note "
    "that it is not medically validated.",
    "We do not publish a recording without the consent of the people who gave it.",
)


def _list(items: tuple[str, ...], numbered: bool) -> None:
    marks = (f"{n}. " for n in range(1, len(items) + 1)) if numbered else ("- " for _ in items)
    st.markdown("\n".join(f"{mark}{item}" for mark, item in zip(marks, items, strict=True)))


def render_how() -> None:
    """How it works, for the people who contribute and the people who read."""
    theme.page_header(
        "How it works",
        "From a voice to an answer you can trace back to who said it.",
        "connections",
    )
    st.subheader("If you share a recording")
    _list(CONTRIBUTORS, numbered=True)
    st.subheader("If you read, listen or ask")
    _list(READERS, numbered=False)
    st.subheader("What happens behind the scenes")
    _list(BEHIND, numbered=False)


def render_about(facts: OrganisationFacts) -> None:
    """Why the project exists, what it will not do, and who runs it."""
    theme.page_header(
        "About HeritageVoice",
        "A community-controlled platform that turns consented oral histories into reviewed, "
        "searchable knowledge.",
        "home",
    )
    st.subheader("Why this project exists")
    for paragraph in WHY:
        st.markdown(paragraph)
    st.subheader("What we will not do")
    _list(WE_DO_NOT, numbered=False)
    st.subheader("Who runs it")
    st.markdown(
        f"HeritageVoice AI is run by **{facts.operator}**. The code is open source, so anyone can "
        f"read how it works: [the project on GitHub]({REPOSITORY})."
    )
    theme.footer()
