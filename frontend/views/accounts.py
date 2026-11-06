"""Accounts (admins): see everyone who has an account, change a role or groups, or disable one.

Changing a role or disabling an account takes effect when the person's sign-in next refreshes
(within about half an hour). You cannot change or disable your own account here, so an admin
cannot lock themselves out.
"""

from html import escape

import streamlit as st

from frontend.api_client import AccountView, ApiClient, ApiError, GroupView
from frontend.messages import message_for
from frontend.roles import ROLE_CHOICES, role_label

DELAY_NOTE = "A change applies when the person's sign-in next refreshes, within about 30 minutes."


def describe_groups(communities: list[str], names: dict[str, str]) -> str:
    """The group names for display; a group that no longer exists is shown by its ID."""
    if not communities:
        return "no groups"
    return ", ".join(names.get(c, c) for c in communities)


def _run(action: object, success: str) -> None:
    try:
        action()  # type: ignore[operator]
    except ApiError as error:
        st.error(message_for(error))
        return
    st.success(success)
    st.rerun()


def _role_form(client: ApiClient, person: AccountView) -> None:
    labels = list(ROLE_CHOICES)
    current = labels.index(role_label(person.role)) if role_label(person.role) in labels else 0
    choice = ROLE_CHOICES[str(st.selectbox("Role", labels, current, key=f"role-{person.sub}"))]
    unchanged = choice == person.role
    if st.button("Save role", key=f"save-role-{person.sub}", disabled=unchanged):
        _run(lambda: client.set_account_role(person.sub, choice), "Role saved.")


def _groups_form(client: ApiClient, person: AccountView, groups: list[GroupView]) -> None:
    names = {g.id: g.name for g in groups}
    known = [c for c in person.communities if c in names]
    chosen = st.multiselect(
        "Groups", list(names), known, format_func=names.__getitem__, key=f"groups-{person.sub}"
    )
    if st.button("Save groups", key=f"save-groups-{person.sub}", disabled=chosen == known):
        _run(lambda: client.set_account_groups(person.sub, chosen), "Groups saved.")


def _disable_form(client: ApiClient, person: AccountView) -> None:
    sure = st.checkbox(
        "I understand this person will be signed out and cannot sign in again.",
        key=f"sure-disable-{person.sub}",
    )
    if st.button("Disable account", key=f"disable-{person.sub}", disabled=not sure):
        _run(lambda: client.disable_account(person.sub), "Account disabled.")


def _controls(client: ApiClient, person: AccountView, groups: list[GroupView]) -> None:
    with st.expander("Change role, groups or access"):
        st.caption(DELAY_NOTE)
        _role_form(client, person)
        _groups_form(client, person, groups)
        st.divider()
        _disable_form(client, person)


def _title(person: AccountView) -> str:
    shown = escape(person.email) if person.email else "<i>account not found in sign-in</i>"
    disabled = "  ·  <b>Disabled</b>" if person.status == "disabled" else ""
    return f"<b>{shown}</b>  ·  {role_label(person.role)}{disabled}"


def _note(person: AccountView) -> str | None:
    """The one line that replaces the controls when there is nothing to change."""
    if person.is_you:
        return "This is you. You cannot change or disable your own account here."
    if person.status == "disabled":
        return "Cannot sign in. Re-enabling is not available in the app yet."
    return None


def _card(client: ApiClient, person: AccountView, groups: list[GroupView]) -> None:
    names = {g.id: g.name for g in groups}
    with st.container(border=True):
        st.markdown(_title(person), unsafe_allow_html=True)
        where = describe_groups(person.communities, names)
        st.caption(f"Joined {person.created} · Groups: {where}")
        note = _note(person)
        if note:
            st.caption(note)
        else:
            _controls(client, person, groups)


def render(client: ApiClient, groups: list[GroupView]) -> None:
    """The Accounts tab: everyone with an account, newest last."""
    try:
        people = client.accounts()
    except ApiError as error:
        st.error(message_for(error))
        return
    st.caption(f"{len(people)} accounts")
    for person in people:
        _card(client, person, groups)
