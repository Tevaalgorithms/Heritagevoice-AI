"""The relationships a proposal can name, in plain words. The keys are what the server stores."""

RELATIONS = {
    "MENTIONS": "mentions",
    "DESCRIBES": "is about",
    "OCCURRED_AT": "happened at",
    "RELATED_TO": "is related to",
    "TEACHES": "teaches",
    "SPOKE_IN": "spoke in",
}


def phrase(relation: str) -> str:
    """The relationship as words, for example `mentions`. Unknown ones are shown as stored."""
    return RELATIONS.get(relation, relation)
