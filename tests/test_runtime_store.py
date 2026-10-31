import logging

from app.runtime_store import RuntimeStore


class Settings:
    def __init__(self, value=None):
        self.value = value


def store(settings, built, fail=False):
    def build(config):
        built.append(config)
        if fail:
            raise RuntimeError("secret detail")
        return f"store-{config}"

    return RuntimeStore(lambda: settings.value, build, "Thing")


def test_there_is_no_store_until_settings_exist():
    built = []
    assert store(Settings(), built).get() is None
    assert built == []


def test_it_is_built_once_and_again_when_the_settings_change():
    settings, built = Settings("a"), []
    runtime = store(settings, built)
    assert (runtime.get(), runtime.get()) == ("store-a", "store-a")
    settings.value = "b"
    assert runtime.get() == "store-b"
    assert built == ["a", "b"]


def test_removing_the_settings_removes_the_store():
    settings = Settings("a")
    runtime = store(settings, [])
    runtime.get()
    settings.value = None
    assert runtime.get() is None


def test_a_failed_build_is_logged_without_its_text_and_tried_again(caplog):
    built = []
    runtime = store(Settings("a"), built, fail=True)
    with caplog.at_level(logging.WARNING):
        assert (runtime.get(), runtime.get()) == (None, None)
    assert built == ["a", "a"]
    assert "Thing could not be set up: RuntimeError" in caplog.text
    assert "secret" not in caplog.text
