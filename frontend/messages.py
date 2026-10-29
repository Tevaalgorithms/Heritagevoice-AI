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
    "forbidden": "You are not a member of that community.",
}


def message_for(error: ApiError) -> str:
    code = getattr(error, "code", None)
    if code in CODE_MESSAGES:
        return CODE_MESSAGES[code]
    matches = (text for kind, text in ERROR_MESSAGES.items() if isinstance(error, kind))
    return next(matches, "Something went wrong.")
