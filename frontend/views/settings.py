"""Admin page: the model catalogue, and for each job a primary model with fall-back models.

API keys are not handled here. Each catalogue entry names the Parameter Store key it uses; the
value lives in AWS Systems Manager Parameter Store (SecureString) and is read by the server when
needed. This page only shows whether each key is configured.
"""

import streamlit as st

from frontend import theme
from frontend.api_client import (
    ApiClient,
    ApiError,
    CatalogView,
    ModelParamsSpec,
    ModelsOverview,
    ModelView,
    NewModelSpec,
)
from frontend.messages import message_for, probe_message

PROVIDERS = ("anthropic",)
STATUSES = ("active", "deprecated", "disabled")
DEFAULT_KEY_NAME = "HERITAGEVOICE_LLM_API_KEY"
NONE = "(none)"
FALLBACK_SLOTS = 3
STATUS_HELP = (
    "**Active** models can be chosen. **Deprecated** models keep working where already chosen. "
    "**Disabled** models serve nothing, so a job moves on to its next fall-back."
)


def _load(client: ApiClient) -> ModelsOverview | None:
    try:
        return client.model_settings()
    except ApiError as error:
        st.error(message_for(error))
        return None


def _run(action: object, success: str) -> None:
    try:
        action()  # type: ignore[operator]
    except ApiError as error:
        st.error(message_for(error))
        return
    st.success(success)
    st.rerun()


def _catalog_rows(catalog: list[CatalogView]) -> list[dict[str, str]]:
    return [
        {
            "Model": entry.model_id,
            "Provider": entry.provider,
            "Status": entry.status,
            "Key name": entry.key_name,
            "Key": "Configured" if entry.key_configured else "Missing",
        }
        for entry in catalog
    ]


def _catalog_table(overview: ModelsOverview) -> None:
    st.subheader("Model catalogue")
    st.caption(STATUS_HELP)
    st.dataframe(_catalog_rows(overview.catalog), hide_index=True, use_container_width=True)
    missing = {e.key_name for e in overview.catalog if not e.key_configured}
    if missing:
        st.warning(
            "Key not found for: "
            + ", ".join(sorted(missing))
            + ". Add each as a SecureString parameter in AWS Systems Manager Parameter Store "
            "under the site's path. It is picked up within a few minutes, with no redeploy."
        )
    st.caption("Keys are never shown, stored in the database or entered on this page.")


def _add_model(client: ApiClient) -> None:
    with st.form("add-model"):
        model_id = st.text_input("Model name", help="Exactly as the provider names it.")
        provider = st.selectbox("Provider", PROVIDERS)
        key_name = st.text_input("Key name", DEFAULT_KEY_NAME, help="The Parameter Store name.")
        if st.form_submit_button("Add to catalogue") and model_id:
            spec = NewModelSpec(
                model_id=model_id.strip(), provider=str(provider), key_name=key_name
            )
            _run(lambda: client.add_model(spec), "Added.")


def _change_status(client: ApiClient, overview: ModelsOverview) -> None:
    ids = [e.model_id for e in overview.catalog]
    if not ids:
        return
    with st.form("model-status"):
        model_id = str(st.selectbox("Model", ids))
        status = str(st.selectbox("New status", STATUSES))
        if st.form_submit_button("Apply"):
            _run(lambda: client.set_model_status(model_id, status), "Updated.")


def _manage_catalog(client: ApiClient, overview: ModelsOverview) -> None:
    with st.expander("Add a model"):
        _add_model(client)
    with st.expander("Change a model's status"):
        _change_status(client, overview)


def _choices(row: ModelView, overview: ModelsOverview) -> list[str]:
    """Active models, plus whatever this job already uses so the page shows its true state."""
    keep = {row.model, *row.fallbacks}
    return [e.model_id for e in overview.catalog if e.status == "active" or e.model_id in keep]


def _provider_of(model_id: str, overview: ModelsOverview, fallback: str) -> str:
    return next((e.provider for e in overview.catalog if e.model_id == model_id), fallback)


def _current_fallback(row: ModelView, slot: int) -> str:
    return row.fallbacks[slot] if slot < len(row.fallbacks) else NONE


def _pick(row: ModelView, options: list[str], slot: int, key: str) -> str:
    current = _current_fallback(row, slot)
    index = options.index(current) if current in options else 0
    return str(st.selectbox(f"Fall-back {slot + 1}", options, index, key=f"{key}-f{slot}"))


def _fallback_picks(row: ModelView, choices: list[str], key: str) -> list[str]:
    options = [NONE, *choices]
    picks = [_pick(row, options, slot, key) for slot in range(FALLBACK_SLOTS)]
    return [p for p in picks if p != NONE]


def _form(row: ModelView, overview: ModelsOverview) -> ModelParamsSpec:
    key = f"model-{row.role}"
    choices = _choices(row, overview)
    index = choices.index(row.model) if row.model in choices else 0
    primary = str(st.selectbox("Primary model", choices, index, key=f"{key}-m"))
    return ModelParamsSpec(
        provider=_provider_of(primary, overview, row.provider),
        model=primary,
        fallbacks=_fallback_picks(row, choices, key),
        temperature=st.slider("Temperature", 0.0, 1.0, row.temperature, 0.05, key=f"{key}-t"),
        timeout_s=st.number_input("Timeout (seconds)", 5.0, 300.0, row.timeout_s, key=f"{key}-s"),
        max_retries=int(st.number_input("Retries", 0, 5, row.max_retries, key=f"{key}-r")),
    )


def _probe(client: ApiClient, role: str, params: ModelParamsSpec) -> None:
    try:
        with st.spinner("Sending a tiny test request…"):
            result = client.probe_model_setting(role, params)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.success("The model answered.") if result.ok else st.error(probe_message(result.code))


def _role_panel(client: ApiClient, overview: ModelsOverview, row: ModelView) -> None:
    st.subheader(row.role.capitalize())
    st.caption(
        "Saved by an admin. If the primary model fails, the fall-backs are tried in order."
        if row.source == "database"
        else "Using the server default (no fall-backs). Save to choose a primary and fall-backs."
    )
    params = _form(row, overview)
    save, test, reset = st.columns(3)
    if save.button("Save", key=f"{row.role}-save"):
        _run(
            lambda: client.save_model_setting(row.role, params),
            "Saved. It applies within a minute.",
        )
    if test.button("Test primary (costs a few tokens)", key=f"{row.role}-test"):
        _probe(client, row.role, params)
    if reset.button("Reset to default", key=f"{row.role}-reset", disabled=row.source == "default"):
        _run(lambda: client.reset_model_setting(row.role), "Reset.")


def render(client: ApiClient) -> None:
    theme.page_header(
        "Model settings",
        "Choose each job's models, with fall-backs if one fails. Keys stay in the secret store.",
        "settings",
    )
    overview = _load(client)
    if overview is None:
        return
    _catalog_table(overview)
    _manage_catalog(client, overview)
    for row in overview.roles:
        _role_panel(client, overview, row)
