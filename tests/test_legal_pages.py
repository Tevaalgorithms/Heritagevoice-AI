"""The legal pages: every one exists, links resolve, and no placeholder is ever left raw."""

import re

import pytest

from frontend.legal import (
    LEGAL_DIR,
    LEGAL_VERSION,
    PAGES,
    UNSET,
    OrganisationFacts,
    legal_text,
)

FACTS = OrganisationFacts("Example Heritage Trust", "legal@example.org", "England and Wales")
SLUGS = {page.slug for page in PAGES}


def test_the_five_expected_documents_exist():
    assert {"terms", "privacy", "acceptable-use", "accessibility", "contact"} == SLUGS
    for page in PAGES:
        assert (LEGAL_DIR / page.file).stat().st_size > 400, page.file


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.slug)
def test_a_page_with_details_set_has_no_raw_placeholders(page):
    text = legal_text(page, FACTS)
    assert "{{" not in text
    assert "Example Heritage Trust" in text or "legal@example.org" in text
    assert LEGAL_VERSION in text


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.slug)
def test_a_page_with_no_details_shows_a_visible_placeholder_never_a_blank(page):
    text = legal_text(page, OrganisationFacts())
    assert "{{" not in text
    assert UNSET["contact"] in text


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.slug)
def test_every_link_between_legal_pages_points_to_a_real_page(page):
    for target in re.findall(r"\]\(/([a-z-]+)\)", (LEGAL_DIR / page.file).read_text()):
        assert target in SLUGS, f"{page.slug} links to /{target}"


def test_the_terms_cover_what_a_heritage_platform_must_say():
    text = legal_text(next(p for p in PAGES if p.slug == "terms"), FACTS)
    for required in (
        "not medically validated",
        "withdraw",
        "train",
        "consent record",
        "governed by the law of **England and Wales**",
    ):
        assert required in text


def test_the_privacy_notice_names_where_data_goes_and_who_handles_it():
    text = legal_text(next(p for p in PAGES if p.slug == "privacy"), FACTS)
    for required in ("United States", "Amazon Web Services", "Pinecone", "multi-factor", "rights"):
        assert required in text


def test_the_privacy_notice_does_not_claim_searches_are_never_logged():
    text = legal_text(next(p for p in PAGES if p.slug == "privacy"), FACTS)
    assert "not kept" not in text
    assert "server logs" in text


def test_the_privacy_notice_says_only_necessary_cookies_are_used():
    text = legal_text(next(p for p in PAGES if p.slug == "privacy"), FACTS)
    assert "only the cookies needed to work" in text
    assert "advertising" in text


def test_the_accessibility_statement_does_not_claim_a_conformance_it_has_not_earned():
    text = legal_text(next(p for p in PAGES if p.slug == "accessibility"), FACTS)
    assert "not yet had" in text
    assert "fully conforms" in text  # only in the negative: "cannot say it fully conforms"
    assert "cannot say it fully conforms" in text
