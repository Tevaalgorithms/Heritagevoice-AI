"""Admin page: choose the model and parameters for each job.

API keys are not handled here. They live in AWS Parameter Store as SecureString parameters and
reach the app as environment variables; this page only shows whether a key is configured.
"""

import streamlit as st

from frontend import theme
from frontend.api_client import (
    ApiClient,
    ApiError,
    ModelParamsSpec,
    ModelsOverview,
    ModelView,
)
from frontend.messages import message_for, probe_message


def _load(client: ApiClient) -> ModelsOverview | None:
    try:
        return client.model_settings()
    except ApiError as error:
        st.error(message_for(error))
        return None


def _key_status(overview: ModelsOverview) -> None:
    if overview.key_configured:
        st.success("A model API key is configured on the server.")
    else:
        st.warning(
            f"No model API key is configured. Store it in AWS Systems Manager Parameter Store "
            f"as a SecureString named {overview.key_name}, then redeploy."
        )
    st.caption("Keys are never shown, stored in the database or entered on this page.")


def _form(row: ModelView, overview: ModelsOverview) -> ModelParamsSpec:
    key = f"model-{row.role}"
    providers = list(overview.allowed)
    provider = st.selectbox("Provider", providers, providers.index(row.provider), key=f"{key}-p")
    models = overview.allowed[provider]
    index = models.index(row.model) if row.model in models else 0
    return ModelParamsSpec(
        provider=provider,
        model=st.selectbox("Model", models, index, key=f"{key}-m"),
        temperature=st.slider("Temperature", 0.0, 1.0, row.temperature, 0.05, key=f"{key}-t"),
        timeout_s=st.number_input("Timeout (seconds)", 5.0, 300.0, row.timeout_s, key=f"{key}-s"),
        max_retries=int(st.number_input("Retries", 0, 5, row.max_retries, key=f"{key}-r")),
    )


def _run(action: object, success: str) -> None:
    try:
        action()  # type: ignore[operator]
    except ApiError as error:
        st.error(message_for(error))
        return
    st.success(success)
    st.rerun()


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
    st.caption("Saved by an admin" if row.source == "database" else "Using the server default")
    params = _form(row, overview)
    save, test, reset = st.columns(3)
    if save.button("Save", key=f"{row.role}-save"):
        _run(
            lambda: client.save_model_setting(row.role, params),
            "Saved. It applies within a minute.",
        )
    if test.button("Test (costs a few tokens)", key=f"{row.role}-test"):
        _probe(client, row.role, params)
    if reset.button("Reset to default", key=f"{row.role}-reset", disabled=row.source == "default"):
        _run(lambda: client.reset_model_setting(row.role), "Reset.")


def render(client: ApiClient) -> None:
    theme.page_header(
        "Model settings",
        "Choose which model does each job. API keys stay in the server's secret store.",
    )
    overview = _load(client)
    if overview is None:
        return
    _key_status(overview)
    for row in overview.roles:
        _role_panel(client, overview, row)
