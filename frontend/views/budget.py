"""Admin: a monthly cost limit that is spent as an equal share each day.

The limit is a guard-rail on the language models. Each day may use the monthly figure divided by
the days in the month (the day runs on UTC); once that share is spent, model calls stop until the
next day and the site falls back to plain search of the text. Costs are estimates from the prices
on the Models tab, so a model without a price is not counted.
"""

import streamlit as st

from frontend.api_client import ApiClient, ApiError, BudgetView
from frontend.messages import message_for

LIMIT_KEY = "budget-monthly"


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _today(budget: BudgetView) -> None:
    spent, left, share = st.columns(3)
    spent.metric("Spent today (estimate)", _money(budget.spent_today))
    if budget.daily_usd is None or budget.remaining_today is None:
        share.metric("Today's share", "No limit")
        left.metric("Left today", "No limit")
        return
    share.metric("Today's share", _money(budget.daily_usd))
    left.metric("Left today", _money(budget.remaining_today))
    st.progress(min(budget.spent_today / budget.daily_usd, 1.0))


def _notes(budget: BudgetView) -> None:
    if budget.exhausted:
        st.warning(
            "Today's share is spent. Language-model calls are paused until tomorrow (UTC). "
            "Searching the text still works, and new recordings wait until a new day or a "
            "higher limit."
        )
    if budget.monthly_usd is not None and budget.unpriced_models:
        st.info(
            "No price set for: " + ", ".join(budget.unpriced_models) + ". Their calls are "
            "not counted against the limit. Add a price on the Models tab."
        )


def _form(client: ApiClient, budget: BudgetView) -> None:
    with st.form("budget-limit", border=False):
        monthly = st.number_input(
            "Monthly limit, US dollars",
            min_value=0.0,
            max_value=1_000_000.0,
            value=budget.monthly_usd or 0.0,
            step=1.0,
            key=LIMIT_KEY,
            help="Spread evenly over the days of the month. Set to 0 to turn the limit off.",
        )
        if st.form_submit_button("Save limit", type="primary"):
            _save(client, monthly or None)


def _save(client: ApiClient, monthly: float | None) -> None:
    try:
        client.set_budget(monthly)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.success("Saved. It applies to the next model call." if monthly else "Limit removed.")
    st.rerun()


def render(client: ApiClient) -> None:
    """The cost limit: today's spending against the day's share, and the monthly figure to edit."""
    st.subheader("Daily cost limit")
    st.caption(
        "Set a monthly budget. Each day may spend that amount divided by the days in the month, "
        "so one busy day cannot use up the month."
    )
    try:
        budget = client.budget()
    except ApiError as error:
        st.error(message_for(error))
        return
    _today(budget)
    _notes(budget)
    _form(client, budget)
