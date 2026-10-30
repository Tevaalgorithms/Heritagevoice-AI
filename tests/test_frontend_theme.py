from app.languages import LANGUAGES
from frontend.theme import supported_languages_html


def test_the_footer_lists_every_supported_language_in_its_own_script():
    html = supported_languages_html()
    assert all(lang.native_name in html for lang in LANGUAGES)
    for name in ("தமிழ்", "हिन्दी", "తెలుగు", "Français"):
        assert name in html


def test_the_footer_line_is_static_text_only():
    assert "<script" not in supported_languages_html().lower()
