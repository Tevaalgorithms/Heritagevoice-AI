"""The languages someone can speak in, as the pickers show them, and the code each one sends."""

from app.languages import LANGUAGES as ALL_LANGUAGES

LANGUAGE_CHOICES = {f"{lang.name} · {lang.native_name}": lang.code for lang in ALL_LANGUAGES}
