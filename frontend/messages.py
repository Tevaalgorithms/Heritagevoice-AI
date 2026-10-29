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


def message_for(error: ApiError) -> str:
    matches = (text for kind, text in ERROR_MESSAGES.items() if isinstance(error, kind))
    return next(matches, "Something went wrong.")
