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
- Audio playback of a cited passage on the Ask page, only for people who may view the recording
  and only while its consent still allows playback. Library cards do not play audio yet.

## Known limits

- Meaning-based (vector) search covers a reader's own communities only. Public recordings from
  other communities are found by keyword search. A shared public vector namespace is not built.
- Video: the upload check accepts the MP4 container (the same check as m4a audio) and the sound
  is meant to be transcribed, but this has not been tried with a real video file yet. Other video
  formats are not accepted.
- There is no "report this item" button, rate limit on search, or anonymous browsing yet.
