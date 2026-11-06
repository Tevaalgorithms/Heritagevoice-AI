"""Groups and consent (admins and coordinators): create the groups people belong to, and record
what each group has allowed. Contributors pick a group and one of its consents when adding a
recording, so nobody types an ID. A coordinator sees only the groups they belong to."""

import streamlit as st

from frontend import theme
from frontend.api_client import ApiClient, ApiError, ConsentView, GroupView, MemberView
from frontend.messages import message_for
from frontend.rights import EVERYDAY, RIGHTS, describe

GROUP_HELP = "For example: My family, Our village, Jaffna elders. The ID is made for you."


def _load_groups(client: ApiClient) -> list[GroupView] | None:
    try:
        return client.groups()
    except ApiError as error:
        st.error(message_for(error))
        return None


def _create_group(client: ApiClient, name: str) -> None:
    try:
        group = client.create_group(name)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.toast(f"Created “{group.name}” (ID {group.id}). You are a member of it.")
    st.rerun()


def _groups_tab(client: ApiClient, groups: list[GroupView]) -> None:
    st.caption("A group is the people who share and look after a set of recordings together.")
    if groups:
        rows = [{"Group": g.name, "ID": g.id} for g in groups]
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("No groups yet. Create the first one below.")
    with st.form("new-group", clear_on_submit=True, border=True):
        name = st.text_input("Group name", placeholder="My family", help=GROUP_HELP)
        created = st.form_submit_button("Create group", type="primary")
    if created and name.strip():
        _create_group(client, name.strip())


def _revoke(client: ApiClient, consent: ConsentView) -> None:
    try:
        client.revoke_consent(consent.id)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.rerun()


def _consent_card(client: ApiClient, consent: ConsentView) -> None:
    with theme.card(f"consent-{consent.id}"):
        state = "Withdrawn" if consent.revoked else "Active"
        st.markdown(f"**{state}** · version {consent.policy_version}")
        st.caption(describe(consent.rights))
        st.code(consent.id, language=None)
        if not consent.revoked and st.button(
            "Withdraw this consent",
            key=f"withdraw-{consent.id}",
            help="Recordings that rely on it stop being shared or processed.",
        ):
            _revoke(client, consent)


def _new_consent(client: ApiClient, group: GroupView) -> None:
    with st.form(f"new-consent-{group.id}", border=True):
        chosen = st.multiselect(
            "What the group allows",
            list(RIGHTS),
            default=list(EVERYDAY),
            format_func=RIGHTS.__getitem__,
        )
        created = st.form_submit_button("Record this consent", type="primary")
    if created and chosen:
        try:
            client.create_consent(group.id, chosen)
        except ApiError as error:
            st.error(message_for(error))
            return
        st.rerun()


def _consent_tab(client: ApiClient, groups: list[GroupView]) -> None:
    st.caption(
        "A consent records what a group has agreed to for its recordings. Contributors pick one "
        "when they add a recording. “Share it publicly” is left unticked unless the group agrees."
    )
    if not groups:
        st.info("Create a group first.")
        return
    group = st.selectbox("Group", groups, format_func=lambda g: g.name)
    try:
        existing = client.consents(group.id)
    except ApiError as error:
        st.error(message_for(error))
        return
    for consent in existing:
        _consent_card(client, consent)
    _new_consent(client, group)


def _add_member(client: ApiClient, group: GroupView, email: str) -> None:
    try:
        client.add_member(group.id, email)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.rerun()


def _remove_member(client: ApiClient, group: GroupView, member: MemberView) -> None:
    try:
        client.remove_member(group.id, member.sub)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.rerun()


def _member_row(client: ApiClient, group: GroupView, member: MemberView) -> None:
    name, action = st.columns([4, 1])
    name.markdown(member.email)
    if action.button("Remove", key=f"remove-{group.id}-{member.sub}"):
        _remove_member(client, group, member)


def _member_list(client: ApiClient, group: GroupView) -> bool:
    """Show who is in the group. False if they could not be loaded."""
    try:
        members = client.members(group.id)
    except ApiError as error:
        st.error(message_for(error))
        return False
    for member in members:
        _member_row(client, group, member)
    return True


def _member_form(client: ApiClient, group: GroupView) -> None:
    with st.form(f"add-member-{group.id}", clear_on_submit=True, border=True):
        email = st.text_input("Add a person by email", placeholder="aunt@example.org")
        added = st.form_submit_button("Add to this group", type="primary")
    if added and email.strip():
        _add_member(client, group, email.strip())


def _members_tab(client: ApiClient, groups: list[GroupView]) -> None:
    st.caption(
        "Add the people of a family or group by email. They need an account that an administrator "
        "has approved, but they create nothing: you set the group up for them."
    )
    if not groups:
        st.info("Create a group first.")
        return
    group = st.selectbox("Group", groups, format_func=lambda g: g.name, key="members-group")
    if _member_list(client, group):
        _member_form(client, group)


def render(client: ApiClient) -> None:
    """The Groups page."""
    theme.page_header(
        "Groups and consent",
        "Set up the groups people belong to, add their people, and record what each allows.",
        "people",
    )
    groups = _load_groups(client)
    if groups is None:
        return
    tab_groups, tab_people, tab_consent = st.tabs(
        [
            ":material/groups: Groups",
            ":material/group_add: People",
            ":material/verified_user: Consent",
        ]
    )
    with tab_groups:
        _groups_tab(client, groups)
    with tab_people:
        _members_tab(client, groups)
    with tab_consent:
        _consent_tab(client, groups)
