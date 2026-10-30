"""One page per legal document. Public: no sign-in is needed to read them."""

import streamlit as st

from frontend import theme
from frontend.legal import LegalPage, OrganisationFacts, legal_text


def render(page: LegalPage, facts: OrganisationFacts) -> None:
    """Show a legal document. The text is a trusted file in the repository, not user input."""
    theme.page_header(page.title, "Please read this carefully. It applies to everyone.", "legal")
    st.markdown(legal_text(page, facts))
