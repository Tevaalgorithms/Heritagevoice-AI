# Sharing: who can read what

HeritageVoice keeps community knowledge private by default. Reading beyond the community is a
deliberate choice that needs consent and an admin's approval. The server enforces every rule
below; the interface only asks.

## Who does what

| Role | Can do |
| --- | --- |
| **Member** (signed in with username and password) | Record or upload audio and MP4 video into a community they belong to. Read the Library: public recordings plus their own communities'. See and edit their own drafts. |
| **Admin** | Everything a member can, plus: review (approve or reject transcripts and translations), publish, change who may read a recording, manage consent records, models and users. Admins act across all communities. |
| The old **reviewer** role | Still exists for compatibility but has no review right. Only admins review. |

An admin cannot approve their own upload; another admin must. A deployment with a single admin can
turn this off with `HERITAGEVOICE_ALLOW_SELF_REVIEW=true`. That removes a safeguard, so use it only
until a second admin exists.

## Visibility

Every recording is one of:

- **Community** (the default): only members of its community can read it.
- **Public**: every signed-in user can read it in the Library. There is no anonymous access.

A recording becomes readable by outsiders only when **all** of these hold, and the check is made
again on every request, so a change takes effect at once:

1. an admin has approved and published it;
2. its consent record allows **indexing** and **public sharing** and has not been withdrawn;
3. its visibility is **public**.

Asking for public at upload is refused unless the consent already allows public sharing. An admin
can widen or narrow visibility on the Review page; each change is recorded in the audit log.
Making a recording private hides it from outsiders immediately, before the search index is rebuilt.

## Traditional remedies

Remedies can be shared publicly like any other kind. Wherever one is shown, the page displays:
**"Not medically validated. Shared from the traditional notes of elders."** The notice comes from
the server with every passage, so it cannot be left out by one screen.

## What readers see

- The passage, in its original language or as the English translation, with its time in the
  recording, and a search that works in every supported script.
- The contributing community's name only if the consent allows attribution. Never the uploader,
  the audio location or the consent record.
- Audio playback, on the Ask page, on Library cards (the cited time range) and on the Review page.
  Anyone, with or without an account, may play a recording only while it is published, shared
  publicly, and its consent allows both public sharing and playback. Everything else is "not
  found". The check runs on every request, so withdrawing a consent or taking an item down
  stops playback at once. Visitors without an account are limited to 10 plays a minute, and the
  audio is never cached or given a storage address.

## Known limits

- Meaning-based (vector) search covers a reader's own communities only. Public recordings from
  other communities are found by keyword search. A shared public vector namespace is not built.
- Video: the upload check accepts the MP4 container (the same check as m4a audio) and the sound
  is meant to be transcribed, but this has not been tried with a real video file yet. Other video
  formats are not accepted.
- Audio is streamed through the API rather than from short-lived storage links, so a withdrawal
  takes effect immediately. Storage links would reduce server traffic, at the cost of a link that
  stays usable for a few minutes; reconsider if playback traffic grows.

## Withdrawing a recording (admins)

On **Review**, choose the recording and open **Withdraw this recording** at the bottom. Give a
reason and tick the confirmation, then press **Withdraw now**.

- **At once:** the recording leaves the Library, search and answers, and playback stops.
- **Shortly after (a background job):** its vectors and relationships are removed from Pinecone and
  the knowledge graph.
- **Kept:** the record itself and your reason, in the audit log, so the decision can be explained.
- **Not reversible** from the app. To share it again, the person uploads it again.

A report from a reader can lead to the same result: Reports → decide → remove.

## Credit and source

When adding a recording, a contributor can give, all optionally:

- a **name to credit** (the speaker, the person who told it, or the author),
- **where the knowledge comes from**: their own knowledge, a family elder, a community elder or
  teacher, a book, a website, or another source,
- a short **note** (for example "my grandmother, from Jaffna" or a book's title and author).

**Who sees it.** The date a recording was added is always shown. The name, source and note are shown
to readers (in the Library and under an answer's sources) only while the recording's consent
includes the **attribution** right; otherwise they stay private. For open sharing the contributor
ticks "Show the name and source with the recording"; for a group, the group's consent decides, and
the form says which applies. If the consent is withdrawn, the credit disappears with the recording.

**What an admin sees.** The Review page shows exactly what was entered, and whether readers will see
it, before the recording is published. Everything entered is shown as plain text, never as a link or
formatting.

The contributor's account (email) is never shown to readers.
