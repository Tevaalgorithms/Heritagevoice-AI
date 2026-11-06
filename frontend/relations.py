"""The relationships a proposal can name, in plain words. The keys are what the server stores."""

from html import escape

RELATIONS = {
    "MENTIONS": "mentions",
    "DESCRIBES": "is about",
    "OCCURRED_AT": "happened at",
    "RELATED_TO": "is related to",
    "TEACHES": "teaches",
    "SPOKE_IN": "spoke in",
}


def headline_html(subject: str, relation: str, obj: str) -> str:
    """`subject relationship object` with the two names in bold; the names are escaped."""
    return f"<b>{escape(subject)}</b> {escape(phrase(relation))} <b>{escape(obj)}</b>"


def phrase(relation: str) -> str:
    """The relationship as words, for example `mentions`. Unknown ones are shown as stored."""
    return RELATIONS.get(relation, relation)
