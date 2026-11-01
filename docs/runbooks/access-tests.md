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

## When something breaks (`tests/test_failure_modes.py`)

| What goes wrong | What the reader gets |
| --- | --- |
| The question takes longer than the deadline (45 s) | A clear "deadline" error and no content |
| The router model is down | The text is searched anyway, with a warning |
| The checking model is down | "Not enough in the recordings": nothing is claimed |
| The writing model is down | The checked claims, shown as they are |
| Every model is down | "Not enough in the recordings", never a server error |
| A step crashes | A plain server error with no prompt or secret text |
| A recording is withdrawn or taken down while the question runs | The answer is withdrawn: "not enough", with the warning `sources_changed` |

Just before an answer is returned, `DeliveryCheck` (`app/retrieval/delivery.py`) asks PostgreSQL
again whether each cited source can still be read by that person. If any cannot, the whole answer
is withdrawn, because it may rest on that source.

Known limit: when the deadline passes, the reader gets the error at once, but the work already
started in the background runs to its end (its model calls still happen and cost money). The
deadline protects the reader, not the bill.
