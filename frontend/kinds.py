"""The kinds of heritage a recording can hold, with plain labels and a small picture each."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    """One kind of heritage a recording can hold, with its label, icon and hint."""

    key: str
    label: str
    icon: str
    hint: str


KINDS = (
    Kind("story", "Story", "📖", "A spoken account, memory or tale"),
    Kind("song", "Song", "🎵", "Family, farming, festival or lullaby songs"),
    Kind("lesson", "Lesson or proverb", "💡", "Wisdom passed down to the next generation"),
    Kind("practice", "Farming or craft practice", "🌾", "How things are grown, made or done"),
    Kind("remedy", "Traditional remedy", "🌿", "Health knowledge held by the community"),
)
BY_KEY = {kind.key: kind for kind in KINDS}
REMEDY_NOTICE = (
    "This records what the community says. It is not medical advice, and nothing here has "
    "been tested for safety. Share only what the people who hold this knowledge agree to share."
)


def label_for(key: str) -> str:
    kind = BY_KEY.get(key)
    return "Recording" if kind is None else f"{kind.icon} {kind.label}"
