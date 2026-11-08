# Demo library

A small synthetic library in nine languages (Tamil, Hindi, Telugu, Malayalam, Bengali, French,
Spanish, Portuguese, English) for demonstrations. The text is in `app/demo_recordings.json`. It is
invented: no speaker, no audio (Listen says the recording cannot be played), and native speakers
have not reviewed it. Every id starts with `demo-`.

## Add it to the live site

GitHub, **Actions**, **seed-demo**, **Run workflow** on `main`, action `seed`. Approve the `prod`
deployment. The recordings are public, approved and indexed, so a visitor with no account sees them.
Running it again adds nothing.

## Take it out

Same workflow with action `remove`. The recordings are withdrawn like any withdrawn recording: they
leave the Library, search and answers at once, and their search entries are deleted. The rows stay,
hidden, so `seed` will not bring them back; use new ids in the file if you need a fresh set.
