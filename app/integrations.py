"""The outside services the platform uses, and which of their settings an admin can change.

Each entry is either a *secret* (an API key or password: written to Parameter Store encrypted,
never shown again) or a *setting* (an index name or a model name: stored as plain text and shown).
Only names listed here, or a language model's own `..._API_KEY`, can be written from the portal, so
the portal can never overwrite the database password, the cookie secret or the sign-in secret.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

LLM_GROUP = "Language models"
PINECONE_GROUP = "Pinecone (meaning-based search)"
LANGSMITH_GROUP = "LangSmith (monitoring)"
NEO4J_GROUP = "Neo4j (knowledge graph)"
VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=:@,-]{1,512}$")
CUSTOM_KEY = re.compile(r"^[A-Z][A-Z0-9_]*_API_KEY$")


class Kind(StrEnum):
    """A secret is never shown again; a setting is shown."""

    SECRET = "secret"
    SETTING = "setting"


@dataclass(frozen=True)
class Integration:
    """One value an admin can set."""

    name: str
    label: str
    kind: Kind
    group: str
    help: str
    default: str | None = None
    planned: bool = False


INTEGRATIONS = (
    Integration(
        "HERITAGEVOICE_LLM_API_KEY",
        "Anthropic API key",
        Kind.SECRET,
        LLM_GROUP,
        "From console.anthropic.com. Used by every Anthropic model in the catalogue.",
    ),
    Integration(
        "OPENAI_API_KEY",
        "OpenAI API key",
        Kind.SECRET,
        LLM_GROUP,
        "From platform.openai.com. Used by every OpenAI model in the catalogue.",
    ),
    Integration(
        "PINECONE_API_KEY",
        "Pinecone API key",
        Kind.SECRET,
        PINECONE_GROUP,
        "From the Pinecone console. Needed for meaning-based search.",
    ),
    Integration(
        "PINECONE_INDEX",
        "Pinecone index name",
        Kind.SETTING,
        PINECONE_GROUP,
        "The index you created in Pinecone. Its dimension must match the dimension below.",
    ),
    Integration(
        "EMBEDDING_MODEL",
        "Embedding model",
        Kind.SETTING,
        PINECONE_GROUP,
        "The Pinecone Inference model that turns text into vectors.",
        default="multilingual-e5-large",
    ),
    Integration(
        "EMBEDDING_DIMENSION",
        "Embedding dimension",
        Kind.SETTING,
        PINECONE_GROUP,
        "How many numbers each vector has. multilingual-e5-large uses 1024.",
        default="1024",
    ),
    Integration(
        "LANGSMITH_API_KEY",
        "LangSmith API key",
        Kind.SECRET,
        LANGSMITH_GROUP,
        "For tracing and evaluating agents. Not used by the app yet.",
        planned=True,
    ),
    Integration(
        "LANGSMITH_PROJECT",
        "LangSmith project",
        Kind.SETTING,
        LANGSMITH_GROUP,
        "Not used by the app yet.",
        planned=True,
    ),
    Integration(
        "NEO4J_URI",
        "Neo4j connection address",
        Kind.SETTING,
        NEO4J_GROUP,
        "From your AuraDB instance (starts with neo4j+s://). Use the Test button after saving.",
    ),
    Integration(
        "NEO4J_USERNAME",
        "Neo4j user name",
        Kind.SETTING,
        NEO4J_GROUP,
        "From the file you downloaded when the instance was created.",
    ),
    Integration(
        "NEO4J_PASSWORD",
        "Neo4j password",
        Kind.SECRET,
        NEO4J_GROUP,
        "From the file you downloaded when the instance was created.",
    ),
)
BY_NAME = {item.name: item for item in INTEGRATIONS}


def resolve(name: str, catalog_key_names: frozenset[str]) -> Integration | None:
    """The definition for a name an admin may write, or None if it must not be written."""
    known = BY_NAME.get(name)
    if known is not None:
        return known
    if name in catalog_key_names and CUSTOM_KEY.match(name):
        return Integration(
            name, f"API key {name}", Kind.SECRET, LLM_GROUP, "Used by a catalogue model."
        )
    return None


def valid_value(value: str) -> bool:
    """Letters, digits and `. _ ~ + / = : @ , -` only, up to 512 characters: what the deploy
    script that reads these values accepts, and nothing that could break out of a config file."""
    return VALUE_PATTERN.fullmatch(value) is not None
