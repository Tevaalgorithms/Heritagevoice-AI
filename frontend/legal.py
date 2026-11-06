"""The legal pages: Terms of Use, Privacy Notice (which covers cookies), Acceptable Use,
Accessibility and Contact.

Their text is in `frontend/legal/*.md`. The organisation's name and contact address are filled in
where the text has {{operator}} and {{contact}}.

These texts describe what the service actually does, but they are a starting point: have a lawyer
who knows the places you operate review them before launch, and set the organisation details.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

LEGAL_VERSION = "2026-10-30"
LEGAL_DIR = Path(__file__).parent / "legal"
OPERATOR = "HeritageVoice Collective"
UNSET = {
    "operator": "[Organisation name]",
    "contact": "[contact email]",
}


@dataclass(frozen=True)
class LegalPage:
    """One legal document: where it lives and what to call it."""

    slug: str
    title: str
    file: str
    icon: str
    summary: str  # one line under the title, specific to the page


PAGES = (
    LegalPage(
        "terms",
        "Terms of Use",
        "terms.md",
        ":material/gavel:",
        "The rules for using HeritageVoice AI. They apply to everyone.",
    ),
    LegalPage(
        "privacy",
        "Privacy Notice",
        "privacy.md",
        ":material/shield:",
        "What we collect, why we collect it, and the choices you have.",
    ),
    LegalPage(
        "acceptable-use",
        "Acceptable Use",
        "acceptable-use.md",
        ":material/rule:",
        "What is welcome here, and what is not.",
    ),
    LegalPage(
        "accessibility",
        "Accessibility",
        "accessibility.md",
        ":material/accessibility_new:",
        "How we aim to serve everyone, and how to tell us about a problem.",
    ),
    LegalPage(
        "contact",
        "Contact and takedown",
        "contact.md",
        ":material/mail:",
        "How to reach us, and how to ask for a recording to be removed.",
    ),
)


@dataclass(frozen=True)
class OrganisationFacts:
    """Who runs the service. Empty values show a visible placeholder, never nothing."""

    operator: str = OPERATOR
    contact: str = ""

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> "OrganisationFacts":
        """The defaults, overridden by HERITAGEVOICE_OPERATOR_NAME and _CONTACT_EMAIL."""
        return cls(
            env.get("HERITAGEVOICE_OPERATOR_NAME", "").strip() or OPERATOR,
            env.get("HERITAGEVOICE_CONTACT_EMAIL", "").strip(),
        )

    def values(self) -> dict[str, str]:
        return {
            "operator": self.operator or UNSET["operator"],
            "contact": self.contact or UNSET["contact"],
            "updated": LEGAL_VERSION,
        }


def legal_text(page: LegalPage, facts: OrganisationFacts) -> str:
    """The page's text with the organisation's details filled in."""
    text = (LEGAL_DIR / page.file).read_text(encoding="utf-8")
    for name, value in facts.values().items():
        text = text.replace("{{" + name + "}}", value)
    return text
