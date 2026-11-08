# Demo library

A small synthetic library in nine languages (Tamil, Hindi, Telugu, Malayalam, Bengali, French,
Spanish, Portuguese, English) for demonstrations. The text is in `app/demo_recordings.json`. It is
invented: there is no real speaker, and native speakers have not reviewed it. Every id starts with
`demo-`.

## Voices

Eight of the nine have a computer-made voice in `app/demo_audio/`, made with the Mac's built-in
voices by `scripts/make_demo_audio.py` (macOS only; commit the new clips). Malayalam has no voice
on a Mac, so that recording has no sound and Listen says it cannot be played. Each clip fills the
same 18 seconds as the recording's segments, so the timings never change. The recordings carry the
source note "Synthetic test recording", and playing one shows "Synthetic voice: computer-generated
speech for testing, not a real speaker" under the player.

## Add it to the live site

GitHub, **Actions**, **seed-demo**, **Run workflow** on `main`, action `seed`. Approve the `prod`
deployment. The recordings are public, approved and indexed, so a visitor with no account sees them.
Running it again adds no recordings, but it stores any missing voice clips, so it is also how
recordings added earlier get their voice.

## Take it out

Same workflow with action `remove`. The recordings are withdrawn like any withdrawn recording: they
leave the Library, search and answers at once, and their search entries are deleted. The rows stay,
hidden, so `seed` will not bring them back; use new ids in the file if you need a fresh set.
