# Languages

People can record in their own language. The list lives in `app/languages.py` (one line per
language) and the server setting `HERITAGEVOICE_ALLOWED_LANGUAGES` decides which are accepted.

## What works today

Tamil, Hindi, Telugu, Malayalam, Kannada, Marathi, Bengali, Gujarati, Punjabi, English, French,
German, Spanish, Italian, Portuguese, Dutch and Russian use
Amazon Transcribe for speech to text. The codes come from its supported-languages table:
<https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html>. Search (keywords)
keeps words whole in all of these scripts. Translation and the later steps use the language model,
which handles many more languages than the speech service does.

"Supported" is not "equally good". Before relying on a language, upload three or four real
recordings, have a native speaker check the transcript, and note the result here.

## Add a language

1. If Amazon Transcribe supports it, add one `Language(...)` line in `app/languages.py` with its
   code (for example `Language("si", "Sinhala", "සිංහල", "si-LK")`) and add the code to
   `HERITAGEVOICE_ALLOWED_LANGUAGES` if you restrict the list.
2. Check its transcript quality with a native speaker.
3. If Transcribe does not support it, keep the audio and have people write the transcript in the
   review editor. Automatic transcription for it is not built yet.

## Not language-specific yet

The embedding model for vector search has not been chosen or tested on these languages. Run the
embedding bake-off (`python -m evals.embedding_bakeoff <model>`) on native-speaker examples first.
Singing and very quiet or noisy recordings transcribe worse than clear speech in any language.
