"""Show passages to a model under short labels, so it can never cite an ID we did not give it.

The model sees `p1`, `p2` ... and answers with those labels. Real evidence IDs stay on our side
and are looked up afterwards; a label that is not in the map is simply ignored. Passage text is
data from a recording, not instructions, and the prompts say so.
"""

from html import escape

from app.models.evidence import Evidence


def label_passages(evidence: list[Evidence]) -> tuple[str, dict[str, Evidence]]:
    """The passages as tagged text for a prompt, and the map from each label to its evidence."""
    labelled = {f"p{number}": item for number, item in enumerate(evidence, start=1)}
    text = "\n".join(
        f'<passage id="{label}">{escape(item.passage)}</passage>'
        for label, item in labelled.items()
    )
    return text, labelled
