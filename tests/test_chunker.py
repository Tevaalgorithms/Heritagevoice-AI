import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.models.transcript import Segment
from app.retrieval.chunker import MAX_TOKENS, chunk_segments
from app.retrieval.tokenize import tokens


def seg(i, text, speaker=None, start=None):
    start = float(i) if start is None else start
    return Segment(segment_id=f"s{i}", start_s=start, end_s=start + 0.5, text=text, speaker=speaker)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("வணக்கம் உலகம்", ["வணக்கம்", "உலகம்"]),
        ("ஏற்றம், கும்மி; பொங்கல்!", ["ஏற்றம்", "கும்மி", "பொங்கல்"]),
        ("Seasonal wells, water-sharing.", ["seasonal", "wells", "water", "sharing"]),
        ("Kummi KUMMI kummi", ["kummi", "kummi", "kummi"]),
        ("village A in 1950", ["village", "a", "in", "1950"]),
        ("  ... ,, ", []),
        ("", []),
    ],
)
def test_tokens_keep_tamil_words_whole_and_drop_punctuation(text, expected):
    assert tokens(text) == expected


def test_a_tamil_word_is_not_cut_at_its_vowel_signs():
    assert tokens("வணக்கம்") == ["வணக்கம்"]


def test_composed_and_decomposed_forms_match():
    composed = "é"
    decomposed = "é"
    assert tokens(composed) == tokens(decomposed)


def test_one_speaker_short_segments_merge_into_one_chunk():
    chunks = chunk_segments([seg(1, "one two"), seg(2, "three four")])
    assert len(chunks) == 1
    assert chunks[0].segment_ids == ("s1", "s2")
    assert (chunks[0].start_s, chunks[0].end_s) == (1.0, 2.5)
    assert chunks[0].text == "one two three four"


def test_a_change_of_speaker_starts_a_new_chunk():
    chunks = chunk_segments([seg(1, "hello", "a"), seg(2, "hi", "b"), seg(3, "ok", "b")])
    assert [(c.speaker, c.segment_ids) for c in chunks] == [("a", ("s1",)), ("b", ("s2", "s3"))]


def test_long_runs_are_capped_and_segments_are_never_split():
    words = " ".join(f"w{i}" for i in range(100))
    chunks = chunk_segments([seg(i, words) for i in range(1, 6)])
    assert [len(c.segment_ids) for c in chunks] == [2, 2, 1]
    assert all(len(tokens(c.text)) <= MAX_TOKENS for c in chunks)


def test_an_oversize_segment_stays_whole_in_its_own_chunk():
    huge = " ".join(f"w{i}" for i in range(MAX_TOKENS * 2))
    chunks = chunk_segments([seg(1, "short"), seg(2, huge), seg(3, "short")])
    assert [c.segment_ids for c in chunks] == [("s1",), ("s2",), ("s3",)]


def test_no_segments_means_no_chunks():
    assert chunk_segments([]) == []


texts = st.text(alphabet=st.sampled_from(list("abc வணக்கம் ஏற்றம்.,")), min_size=1, max_size=400)
speakers = st.sampled_from([None, "a", "b"])


@st.composite
def transcripts(draw):
    count = draw(st.integers(min_value=0, max_value=25))
    return [
        Segment(
            segment_id=f"s{i}",
            start_s=float(i),
            end_s=i + 0.5,
            text=draw(texts) + "x",
            speaker=draw(speakers),
        )
        for i in range(count)
    ]


@given(transcripts())
def test_every_segment_lands_in_exactly_one_chunk_in_order(segments):
    chunks = chunk_segments(segments)
    flat = [sid for chunk in chunks for sid in chunk.segment_ids]
    assert flat == [s.segment_id for s in segments]
    assert [c.index for c in chunks] == list(range(len(chunks)))


@given(transcripts())
def test_chunks_have_one_speaker_a_valid_time_range_and_respect_the_cap(segments):
    by_id = {s.segment_id: s for s in segments}
    for chunk in chunk_segments(segments):
        members = [by_id[sid] for sid in chunk.segment_ids]
        assert {m.speaker for m in members} == {chunk.speaker}
        assert chunk.start_s == members[0].start_s
        assert chunk.end_s == members[-1].end_s
        assert chunk.end_s > chunk.start_s
        assert len(tokens(chunk.text)) <= MAX_TOKENS or len(members) == 1
