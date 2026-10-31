"""What a consent can allow, in plain words. The keys are the rights the server knows."""

RIGHTS = {
    "playback": "Keep the recording and let the group listen to it",
    "ai_processing": "Let AI write down what is said (transcribe)",
    "translation": "Let AI translate it",
    "indexing": "Make it searchable",
    "summarization": "Let AI summarise it when answering questions",
    "attribution": "Name the group when it is shared",
    "public_sharing": "Share it publicly, with anyone who searches",
}
EVERYDAY = ("playback", "ai_processing", "translation", "indexing", "attribution")


def describe(rights: list[str]) -> str:
    """The rights of a consent as a short list of plain phrases."""
    return "; ".join(RIGHTS.get(right, right) for right in rights)
