# Access tests

The rule: a person sees, hears or is told only what the people who shared it allowed, right now.
`tests/test_access_leaks.py` checks this against the whole API with a real database.

## What it covers

Each case builds a recording, indexes it, then changes its state, so a leftover search result is
also tested. Three readers try each surface: a member of the community, a signed-in outsider and a
visitor with no account.

| State of the recording | Found and cited | Audio plays |
| --- | --- | --- |
| Community only | members | members |
| Shared publicly | everyone | everyone |
| Public, but consent lacks public sharing | members | members |
| Public, but consent lacks playback | everyone | nobody |
| Consent forbids indexing and AI processing | nobody | everyone (public) |
| Sent back to review after being indexed | nobody | nobody outside the uploader and admins |
| Consent withdrawn after being indexed | nobody | nobody |
| Taken down after being indexed | nobody | nobody |

Surfaces: Library search (signed in and open), questions (`/v1/query`), audio (signed in and
open), and the recording record. An outsider's refusal looks the same as for a recording that does
not exist. Elsewhere in the suite: reviewer forgeries, stale versions and hidden graph edges
(`test_review_api.py`, `test_graph_search.py`).

## Run it

```sh
uv run pytest tests/test_access_leaks.py
```

Any failure is a release blocker. Do not change an expectation in the table to make a test pass
unless the rule itself was meant to change; then update this page in the same pull request.
