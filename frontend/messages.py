"""Plain-language messages for each client failure. One table instead of branching."""

from frontend.api_client import (
    ApiError,
    ApiNotConfiguredError,
    ApiNotReadyError,
    ApiRequestError,
    ApiUnavailableError,
)

ERROR_MESSAGES: dict[type[ApiError], str] = {
    ApiNotConfiguredError: "Set HERITAGEVOICE_DEV_API_TOKEN in .env to contact the API.",
    ApiUnavailableError: "The API is unavailable. Start it using the setup guide.",
    ApiNotReadyError: "The agent integrations are not ready yet.",
    ApiRequestError: "The request could not be completed.",
}


CODE_MESSAGES = {
    "unsupported_type": "That file is not a supported audio format (WAV, MP3, FLAC, OGG or M4A).",
    "too_large": "That file is too large.",
    "too_long": "That recording is longer than the allowed duration.",
    "empty": "That file is empty.",
    "unreadable": "That audio file could not be read. It may be damaged.",
    "bad_language": "That language is not supported.",
    "consent_denied": "Processing consent is missing, withdrawn or does not cover this recording.",
    "forbidden": "You are not allowed to do that here.",
    "stale_version": "Someone else changed this draft. Reload to see the latest version.",
    "not_reviewable": "This item is not waiting for review (decided, revoked or processing).",
    "transcript_not_approved": "Approve the current transcript first, then its translation.",
    "unknown_segment": "One of the edited segments no longer exists. Reload and try again.",
    "model_exists": "That model is already in the catalogue. Deprecate or disable it instead.",
    "model_not_available": "Every model in the chain must be active, and each can appear once.",
    "unknown_model": "That model is not in the catalogue.",
    "unavailable": "Answers are not available right now. Please try again in a few minutes.",
    "invalid_value": (
        "That value has characters that are not allowed. "
        "Use letters, digits and . _ ~ + / = : @ , - only."
    ),
    "unknown_integration": "That setting is not one the portal manages.",
    "write_denied": (
        "This server is not yet allowed to save keys. "
        "Apply the latest infrastructure change, then try again."
    ),
    "write_failed": "The key could not be saved. Try again in a minute.",
    "not_configured": "Saving is not set up on this server.",
    "not_signed_up": (
        "Nobody has an account with that email. Ask them to create one on the home page first."
    ),
    "not_approved": "That person has an account but an administrator has not approved it yet.",
    "rate_limited": "Too many requests just now. Please wait a few minutes and try again.",
    "invalid_edit": "The two sides of a relationship must be different.",
    "deadline": "That took too long to answer. Try a shorter or simpler question.",
}


def message_for(error: ApiError) -> str:
    code = getattr(error, "code", None)
    if code in CODE_MESSAGES:
        return CODE_MESSAGES[code]
    matches = (text for kind, text in ERROR_MESSAGES.items() if isinstance(error, kind))
    return next(matches, "Something went wrong.")


PROBE_MESSAGES = {
    "no_index": "No Pinecone index name is saved yet.",
    "unknown_index": "Pinecone does not know that index name.",
    "dimension_mismatch": "The index has a different dimension than the one saved here.",
    "no_settings": "The Neo4j address, user name or password is not saved yet.",
    "bad_address": "The Neo4j address must start with neo4j+s:// (copy it from the instance).",
    "bad_credentials": "Neo4j rejected the user name or password.",
    "unreachable": (
        "Neo4j could not be reached. Check the address and that the instance is running."
    ),
    "no_key": "No API key is configured on the server, so the model cannot be tested.",
    "bad_key": "The provider rejected the configured API key.",
    "unknown_model": "The provider does not know this model name.",
    "rate_limited": "The provider is rate limiting requests. Try again in a minute.",
    "provider_error": "The provider returned an error. Check the model and try again.",
}


def probe_message(code: str | None) -> str:
    return PROBE_MESSAGES.get(code or "", "The test failed.")
