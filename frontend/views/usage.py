"""Admin: what the language models were used for, with tokens and an estimated cost.

Costs are estimates from the price per million tokens an admin entered for each model (Models tab,
"Set a model's price"). Only counts are shown; no questions, answers or recordings.
"""

import streamlit as st

from frontend.api_client import ApiClient, ApiError, UsageView
from frontend.messages import message_for

PERIODS = {"Last 24 hours": 1, "Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}
TASKS = {
    "translation": "Translation",
    "supervisor": "Question routing and rewriting",
    "verifier": "Checking the evidence",
    "answer": "Writing answers",
    "graph": "Finding relationships",
}


def _money(value: float | None) -> str:
    return "no price set" if value is None else f"${value:,.4f}"


def _rows(usage: UsageView) -> list[dict[str, str | int]]:
    return [
        {
            "Task": TASKS.get(line.role, line.role),
            "Model": line.model,
            "Calls": line.calls,
            "Input tokens": line.input_tokens,
            "Output tokens": line.output_tokens,
            "Estimated cost": _money(line.cost),
        }
        for line in usage.lines
    ]


def _totals(usage: UsageView) -> None:
    calls, tokens, cost = st.columns(3)
    calls.metric("Model calls", f"{usage.calls:,}")
    tokens.metric("Tokens (in + out)", f"{usage.input_tokens + usage.output_tokens:,}")
    cost.metric("Estimated cost", f"${usage.cost:,.4f}")


def _show(usage: UsageView) -> None:
    _totals(usage)
    if usage.unpriced_models:
        st.info(
            "No price set for: " + ", ".join(usage.unpriced_models) + ". Their tokens are counted, "
            "but not their cost. Add a price on the Models tab."
        )
    if not usage.lines:
        st.write("No model calls in this period yet.")
        return
    st.dataframe(_rows(usage), hide_index=True, use_container_width=True)


def render(client: ApiClient) -> None:
    """The Usage tab: pick a period, see totals and a line per task and model."""
    period = st.radio("Period", list(PERIODS), horizontal=True, key="usage-period")
    try:
        usage = client.usage(PERIODS[str(period)])
    except ApiError as error:
        st.error(message_for(error))
        return
    _show(usage)
    st.caption("Tokens come from the provider's own count. Costs are estimates, not invoices.")
