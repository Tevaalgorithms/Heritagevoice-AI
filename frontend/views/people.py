"""People (admin only): approve or decline new accounts, and invite people, including new admins.

Anyone can create an account, but it can do nothing until an administrator approves it here and
chooses the communities it may add recordings to. Administrators are never approved from a
sign-up: the only way to make one is to invite them on the second tab.
"""

from html import escape

import streamlit as st

from frontend import theme
from frontend.api_client import ApiClient, ApiError, ApiRequestError, SignupView
from frontend.messages import message_for

NOT_FOUND = 404
ROLES = {"Contributor": "member", "Administrator": "admin"}
COMMUNITY_HELP = (
    "Type a community ID and press Enter. Use the same ID the community's consent uses."
)


def _communities(client: ApiClient) -> list[str]:
    try:
        return client.me().communities
    except ApiError:
        return []


def _failure(error: ApiError) -> str:
    gone = isinstance(error, ApiRequestError) and error.status_code == NOT_FOUND
    return "That request is no longer waiting. Refresh the page." if gone else message_for(error)


def _decide(action: str, client: ApiClient, sub: str, communities: list[str]) -> None:
    try:
        if action == "approve":
            client.approve_signup(sub, communities)
        else:
            client.decline_signup(sub)
    except ApiError as error:
        st.error(_failure(error))
    else:
        st.rerun()


def _request_card(client: ApiClient, person: SignupView, options: list[str]) -> None:
    with st.container(border=True):
        st.markdown(f"<b>{escape(person.email)}</b>", unsafe_allow_html=True)
        st.caption(f"Asked for an account on {person.created}. Their email has been verified.")
        chosen = st.multiselect(
            "Communities they may add recordings to",
            options,
            accept_new_options=True,
            help=COMMUNITY_HELP,
            key=f"communities-{person.sub}",
        )
        approve, decline, _ = st.columns([1, 1, 3])
        if approve.button(
            "Approve", type="primary", key=f"approve-{person.sub}", disabled=not chosen
        ):
            _decide("approve", client, person.sub, chosen)
        if decline.button("Decline", key=f"decline-{person.sub}"):
            _decide("decline", client, person.sub, [])


def _waiting_tab(client: ApiClient) -> None:
    try:
        people = client.signups()
    except ApiError as error:
        st.error(message_for(error))
        return
    if not people:
        st.info("Nobody is waiting. New requests appear here once the person confirms their email.")
        return
    st.caption(f"{len(people)} waiting, oldest first")
    options = _communities(client)
    for person in people:
        _request_card(client, person, options)


def _invite_tab(client: ApiClient) -> None:
    st.caption(
        "Invite someone by email. They receive a temporary password and set their own. "
        "Choose Administrator only for people who should review recordings and manage settings."
    )
    with st.form("invite", border=True):
        email = st.text_input("Email address")
        role = st.radio("Role", list(ROLES), horizontal=True)
        communities = st.multiselect(
            "Communities", _communities(client), accept_new_options=True, help=COMMUNITY_HELP
        )
        sent = st.form_submit_button("Send invitation", type="primary")
    if sent:
        _send_invite(client, email.strip(), ROLES[role], communities)


def _send_invite(client: ApiClient, email: str, role: str, communities: list[str]) -> None:
    try:
        client.invite_user(email, role, communities)
    except ApiError as error:
        st.error(message_for(error))
    else:
        st.success(f"Invitation sent to {email}.")


def render(client: ApiClient) -> None:
    """The People page."""
    theme.page_header(
        "People",
        "Approve people who asked for an account, and invite contributors and administrators.",
        "people",
    )
    waiting, invite = st.tabs(
        [":material/how_to_reg: Waiting for approval", ":material/mail: Invite"]
    )
    with waiting:
        _waiting_tab(client)
    with invite:
        _invite_tab(client)
