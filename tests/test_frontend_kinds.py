from frontend.kinds import BY_KEY, KINDS, REMEDY_NOTICE, label_for


def test_every_kind_has_a_label_a_picture_and_a_hint():
    assert [kind.key for kind in KINDS] == ["story", "song", "lesson", "practice", "remedy"]
    assert all(kind.label and kind.icon and kind.hint for kind in KINDS)


def test_labels_combine_the_picture_and_the_name():
    assert label_for("song") == f"{BY_KEY['song'].icon} Song"


def test_an_unknown_kind_gets_a_neutral_label():
    assert label_for("something-new") == "Recording"


def test_the_remedy_notice_says_it_is_not_medical_advice():
    assert "not medical advice" in REMEDY_NOTICE
