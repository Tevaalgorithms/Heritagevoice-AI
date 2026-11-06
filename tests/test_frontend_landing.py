"""The landing, How it works and About pages: fixed text that makes no promise the service does not
keep, and cards the page can lay out."""

import pytest

from frontend import theme
from frontend.legal import OrganisationFacts
from frontend.views import about, home


def test_the_cards_use_the_grid_with_the_right_number_of_columns():
    html = theme.cards_html(home.PRINCIPLES, 4)
    assert "hv-cards cols4" in html
    assert html.count("<div class='hv-card'>") == len(home.PRINCIPLES) == 4
    assert theme.cards_html(home.HOW, 3).count("<div class='hv-card'>") == 3


@pytest.mark.parametrize(
    "texts",
    [home.HOW, home.PRINCIPLES],
    ids=["how", "principles"],
)
def test_every_card_has_a_title_and_a_sentence(texts):
    for title, text in texts:
        assert title.strip()
        assert text.strip().endswith(".")
        assert "<" not in title + text  # fixed text, never markup


@pytest.mark.parametrize(
    "items",
    [about.CONTRIBUTORS, about.READERS, about.BEHIND, about.WHY, about.WE_DO_NOT],
    ids=["contributors", "readers", "behind", "why", "we do not"],
)
def test_every_about_paragraph_is_a_full_sentence(items):
    assert items
    for text in items:
        assert text.strip().endswith(".")


def test_the_pages_keep_the_promises_the_privacy_notice_makes():
    behind = " ".join(about.BEHIND + about.WE_DO_NOT)
    assert "only text" in behind  # audio is never sent to the language models
    assert "no advertising or analytics trackers" in behind
    assert "not medically validated" in behind
    assert "consent" in behind


def test_the_about_page_names_who_runs_it_and_links_to_the_code():
    assert about.REPOSITORY.startswith("https://github.com/")
    facts = OrganisationFacts("Example Heritage Trust", "legal@example.org")
    assert facts.operator == "Example Heritage Trust"


def test_words_heard_by_voice_are_put_in_the_search_box_before_it_is_drawn():
    """Streamlit forbids changing a box's value after it is drawn, so the words wait in a
    separate key and are moved into the box at the start of the next run."""
    from streamlit.testing.v1 import AppTest  # noqa: PLC0415

    def script():
        import streamlit as st  # noqa: PLC0415

        from frontend.views import connections  # noqa: PLC0415

        st.write(connections._search())

    app = AppTest.from_function(script)
    app.session_state["connections-heard"] = "பணிவு"
    app.run()
    assert not app.exception
    assert app.text_input[0].value == "பணிவு"
    assert "connections-heard" not in app.session_state
