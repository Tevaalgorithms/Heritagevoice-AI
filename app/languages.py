"""The spoken languages a recording can be in, and how each maps to the speech service.

One list, used by the API (what it accepts), the speech adapter and the Upload page. The codes
are Amazon Transcribe's, from its supported-languages table. Support does not mean equal quality:
check a few real recordings before relying on a language (see the language runbook note).
Adding a language is one line here plus `HERITAGEVOICE_ALLOWED_LANGUAGES`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    native_name: str
    transcribe_code: str


LANGUAGES = (
    Language("ta", "Tamil", "தமிழ்", "ta-IN"),
    Language("hi", "Hindi", "हिन्दी", "hi-IN"),
    Language("te", "Telugu", "తెలుగు", "te-IN"),
    Language("ml", "Malayalam", "മലയാളം", "ml-IN"),
    Language("kn", "Kannada", "ಕನ್ನಡ", "kn-IN"),
    Language("mr", "Marathi", "मराठी", "mr-IN"),
    Language("bn", "Bengali", "বাংলা", "bn-IN"),
    Language("gu", "Gujarati", "ગુજરાતી", "gu-IN"),
    Language("pa", "Punjabi", "ਪੰਜਾਬੀ", "pa-IN"),
    Language("en", "English", "English", "en-US"),
)
BY_CODE = {language.code: language for language in LANGUAGES}
TRANSCRIBE_CODES = {language.code: language.transcribe_code for language in LANGUAGES}
DEFAULT_ALLOWED = ",".join(language.code for language in LANGUAGES)
