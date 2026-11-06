"""One page per legal document. Public: no sign-in is needed to read them."""

import streamlit as st

from frontend.legal import LegalPage, OrganisationFacts, legal_text


def render(page: LegalPage, facts: OrganisationFacts) -> None:
    """Show a legal document. The text is a trusted file in the repository, not user input."""
    # Plain, like legal pages elsewhere: a title and one line, without the decorative icon tile.
    st.header(page.title)
    st.markdown(f"<p class='hv-sub'>{page.summary}</p>", unsafe_allow_html=True)
    st.markdown(legal_text(page, facts))
