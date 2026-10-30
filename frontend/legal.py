"""The legal pages: Terms of Use, Privacy Notice (which covers cookies), Acceptable Use,
Accessibility and Contact.

Their text is in `frontend/legal/*.md`. The organisation's name, contact address and governing law
are filled in where the text has {{operator}}, {{contact}} and {{jurisdiction}}.

These texts describe what the service actually does, but they are a starting point: have a lawyer
who knows the places you operate review them before launch, and set the organisation details.
"""

from dataclasses import dataclass
from pathlib import Path

LEGAL_VERSION = "2026-10-30"
LEGAL_DIR = Path(__file__).parent / "legal"
UNSET = {
    "operator": "[Organisation name]",
    "contact": "[contact email]",
    "jurisdiction": "[country or state]",
}


@dataclass(frozen=True)
class LegalPage:
    """One legal document: where it lives and what to call it."""

    slug: str
    title: str
    file: str
    icon: str


PAGES = (
    LegalPage("terms", "Terms of Use", "terms.md", ":material/gavel:"),
    LegalPage("privacy", "Privacy Notice", "privacy.md", ":material/shield:"),
    LegalPage("acceptable-use", "Acceptable Use", "acceptable-use.md", ":material/rule:"),
    LegalPage("accessibility", "Accessibility", "accessibility.md", ":material/accessibility_new:"),
    LegalPage("contact", "Contact and takedown", "contact.md", ":material/mail:"),
)


@dataclass(frozen=True)
class OrganisationFacts:
    """Who runs the service. Empty values show a visible placeholder, never nothing."""

    operator: str = ""
    contact: str = ""
    jurisdiction: str = ""

    def values(self) -> dict[str, str]:
        return {
            "operator": self.operator or UNSET["operator"],
            "contact": self.contact or UNSET["contact"],
            "jurisdiction": self.jurisdiction or UNSET["jurisdiction"],
            "updated": LEGAL_VERSION,
        }


def legal_text(page: LegalPage, facts: OrganisationFacts) -> str:
    """The page's text with the organisation's details filled in."""
    text = (LEGAL_DIR / page.file).read_text(encoding="utf-8")
    for name, value in facts.values().items():
        text = text.replace("{{" + name + "}}", value)
    return text
