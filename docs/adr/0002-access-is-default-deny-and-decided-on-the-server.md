# 0002. Access is default-deny and decided on the server

**Status:** Accepted

## Context
The recordings belong to families and communities, who must be able to decide who may hear them and
to change their mind. Language models can be talked into things, and a browser can send anything.

## Decision
- Who may see what is computed on the server from the signed-in user's role and groups (the
  *principal*), and from the recording's consent. Unknown or restricted labels are denied.
- Nothing a client, a prompt or a model says can widen access. Models route and write; they never
  grant.
- The eligibility check runs inside retrieval and again just before an answer is returned.
- Each consent right (play, AI processing, translation, indexing, summarisation, crediting, public
  sharing) is granted separately; none implies another.

## Consequences
- Every access rule has a test for the denied case (see the access-tests runbook).
- Features that would be convenient for a model to decide (who is "probably allowed") are
  deliberately impossible.
- Credit for a speaker is shown only when the consent includes crediting.
- Some answers are shorter than they could be, because restricted passages are never candidates.
