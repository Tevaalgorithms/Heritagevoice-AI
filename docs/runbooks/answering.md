# Answering questions

`POST /v1/query` answers a question for the signed-in reader, from the recordings that reader may
read, with citations. The Ask page uses it.

## The steps (`app/graph/workflow.py`)

1. **Supervisor** decides how to search: text (`hybrid`), relationships (`graph`), both, ask for
   clarification, or refuse (personal medical, legal or safety advice; private details about people;
   attempts to change the rules). It only chooses a route. If the model is unavailable it searches
   the text. The graph is not built yet, so graph routes are answered from the text with the warning
   `graph_unavailable`.
2. **Hybrid retrieval** finds passages (keyword plus vector, fused; see `retrieval.md`).
3. **Verifier** reads the passages and returns the claims they support, how fully they cover the
   question, and any points where accounts disagree. If coverage is not full it may suggest one new
   search; the graph then searches once more (never twice) and keeps the earlier passages too.
4. **Answer writer** writes the answer from the verified claims only. Citations are built in code
   from the claims, never taken from the model. Remedy notices and "accounts differ" lines are added
   by code.
5. **Final gate**: every cited passage is checked again against the reader's permissions.

## What comes back

`status` is one of `answered`, `partial`, `insufficient_evidence`, `clarify`, `refused`. Citations
carry the passage, its start and end time and any notice, and nothing else: no community, access
labels, uploader or storage path. `warnings` lists degraded steps, for example
`vector_search_unavailable`, `graph_unavailable`, `supervisor_unavailable`,
`verification_unavailable`, `answer_writer_unavailable`.

## Safety rules the code enforces

- No passages means no model is asked and the answer is "not enough". Nothing is made up.
- The model sees passages under labels (`p1`, `p2`). A claim citing a label it was never shown is
  dropped. If the verifier fails, nothing is claimed. If the writer fails, the verified claims
  themselves are shown.
- Passage and question text is escaped and wrapped as data; prompts tell models never to follow it.
- A question taking longer than `HERITAGEVOICE_QUERY_DEADLINE_S` (45 s) answers `504 deadline`.
  Any permission failure inside the graph answers a generic `503`, never details.

## Models

Each job has its own primary model and fall-backs on the Settings page: `supervisor` (also used to
rewrite follow-up questions), `verifier`, `answer` and `graph` (see `models.md`). Until a key is configured every model call fails safely, so
questions answer "not enough" or fall back as above.

## Limits

- Text and graph search run one after the other, not in parallel.
- Conversation memory is stateless: the page sends the last few exchanges and a small step rewrites
  a follow-up into a standalone question. Nothing is stored on the server, and `conversation_id` is
  only echoed back.
- The prompts and the checks around them are tested with fake models; answer quality needs real
  runs on your own recordings.
