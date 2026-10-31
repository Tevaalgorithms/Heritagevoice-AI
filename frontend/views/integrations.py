"""Admin portal: keys and settings for the outside services.

Keys are sent once to the server, stored encrypted in AWS Parameter Store and never shown again.
This page can only say whether each one is set. Plain settings (an index name) are shown.
"""

import streamlit as st

from frontend.api_client import (
    ApiClient,
    ApiError,
    IntegrationGroup,
    IntegrationItem,
    IntegrationsOverview,
)
from frontend.messages import message_for, probe_message

MODELS_GROUP = "Language models"
SAVED_SECRET = "Saved. It is used within about five minutes. It is never shown again."
SAVED_SETTING = "Saved."


def _load(client: ApiClient) -> IntegrationsOverview | None:
    try:
        return client.integrations()
    except ApiError as error:
        st.error(message_for(error))
        return None


def _needed(group: IntegrationGroup) -> list[IntegrationItem]:
    """The values a service cannot work without: its secrets, and settings with no default."""
    return [item for item in group.items if item.kind == "secret" or not item.default]


def _is_ready(group: IntegrationGroup) -> bool:
    """Ready when every needed value is set. For language models one key is enough, because they
    are alternatives: the product needs at least one provider, not all of them."""
    if group.label == MODELS_GROUP:
        return any(item.configured for item in group.items)
    return all(item.configured for item in _needed(group))


def _state(group: IntegrationGroup) -> tuple[str, str]:
    """An icon and a short phrase for how far a service is set up."""
    if all(item.planned for item in group.items):
        return ":material/schedule:", "not used yet"
    if _is_ready(group):
        return ":material/check_circle:", "ready"
    return ":material/error:", "needs setting up"


def _checklist(overview: IntegrationsOverview) -> None:
    """One line per service the product needs, so an admin sees what is left to set up."""
    st.subheader("Setup checklist")
    for group in overview.groups:
        icon, phrase = _state(group)
        st.markdown(f"{icon} **{group.label}**: {phrase}")


def _status(item: IntegrationItem) -> str:
    if item.configured:
        return "Configured"
    return "Using the default" if item.default else "Missing"


def _save(client: ApiClient, item: IntegrationItem, value: str) -> None:
    try:
        client.save_integration(item.name, value.strip())
    except ApiError as error:
        st.error(message_for(error))
        return
    st.success(SAVED_SECRET if item.kind == "secret" else SAVED_SETTING)
    st.rerun()


def _secret_field(client: ApiClient, item: IntegrationItem) -> None:
    """A write-only box: the key is sent once, the box empties, and it is never shown again."""
    with st.form(f"int-{item.name}", clear_on_submit=True, border=False):
        value = st.text_input(
            "New key",
            type="password",
            autocomplete="off",
            placeholder="Paste the key here",
            key=f"int-input-{item.name}",
            label_visibility="collapsed",
        )
        label = "Replace" if item.configured else "Save"
        if st.form_submit_button(label) and value:
            _save(client, item, value)


def _setting_field(client: ApiClient, item: IntegrationItem) -> None:
    with st.form(f"int-{item.name}", border=False):
        value = st.text_input(
            "Value",
            value=item.value or item.default or "",
            key=f"int-input-{item.name}",
            label_visibility="collapsed",
        )
        if st.form_submit_button("Save") and value:
            _save(client, item, value)


def _field(client: ApiClient, item: IntegrationItem) -> None:
    (_secret_field if item.kind == "secret" else _setting_field)(client, item)


def _item(client: ApiClient, item: IntegrationItem) -> None:
    with st.container(border=True):
        head, status = st.columns([4, 1])
        head.markdown(f"**{item.label}**" + (" · not used yet" if item.planned else ""))
        status.markdown(f":green[**{_status(item)}**]" if item.configured else _status(item))
        st.caption(item.help)
        _field(client, item)


def _pinecone_test(client: ApiClient) -> None:
    if st.button("Test the Pinecone connection", icon=":material/network_check:"):
        try:
            result = client.test_pinecone()
        except ApiError as error:
            st.error(message_for(error))
            return
        st.success("Pinecone answered and the index matches.") if result.ok else st.error(
            probe_message(result.code)
        )


def _group(client: ApiClient, group: IntegrationGroup) -> None:
    st.subheader(group.label)
    for item in group.items:
        _item(client, item)
    if group.label.startswith("Pinecone"):
        _pinecone_test(client)


def render(client: ApiClient) -> None:
    """The keys and services tab of the Settings page."""
    overview = _load(client)
    if overview is None:
        return
    st.info(
        "Keys are stored encrypted in AWS and are never shown again. To change one, paste a new "
        "value. Settings take effect within about five minutes, with no redeploy.",
        icon=":material/lock:",
    )
    _checklist(overview)
    for group in overview.groups:
        _group(client, group)
