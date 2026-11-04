# Correcting a relationship by voice

Admins can fix a proposed relationship by speaking in their own language instead of typing.

## How it works

1. On **Relationships → To review**, open **Modify: speak or type a correction**.
2. Pick the language, record, and press **Understand my correction**.
3. The server stores the audio under `corrections/<proposal id>/…`, transcribes it with Amazon
   Transcribe, translates it to English, and asks the **graph** model (Settings → Models) what
   relationship the reviewer meant. The audio is deleted in a `finally`, so it goes even if a step
   fails.
4. The page shows what was heard (in the speaker's language and in English) and fills the form with
   the suggestion. The reviewer changes anything, then presses **Approve with these corrections**.
   That is the normal decision step: a person always approves.

## What is and is not kept

- **Not kept:** the audio, the transcript and the translation. Nothing about the correction is
  saved, and the proposal is unchanged until the reviewer approves.
- **Kept:** one audit entry (`graph:voice`, the proposal ID, who). Never the words or the audio.
- **Usage:** the model calls appear under the *graph* job on Settings → Usage and cost.

## Limits and errors

| Limit | Value |
|---|---|
| Length | 60 seconds |
| Rate | 6 per minute per admin |
| Time allowed | 120 seconds, then "That took too long" |

| What the admin sees | Meaning |
|---|---|
| We could not understand that recording | Speech-to-text or a model failed. Try again, or type it. |
| I could not tell what to change | Heard fine, but the correction was unclear or only agreed. Record again, or type it. |
| Not reviewable | The proposal was already decided. |
| Integrations not ready | Speech-to-text is not configured on this server. |

## Known gap

If the server stops in the middle of a call, the temporary audio could stay in the bucket. A
bucket lifecycle rule that expires `corrections/` after a day would remove such leftovers.
