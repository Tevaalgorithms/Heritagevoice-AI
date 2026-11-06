"""Shell with navigation by role. The API token stays on the Streamlit server."""

import os
from collections.abc import Callable

import streamlit as st

from app.config import Settings
from frontend import theme
from frontend.account import (
    AwaitingApprovalError,
    SessionExpiredError,
    current_role,
    show_account,
)
from frontend.api_client import ApiClient, ApiError
from frontend.auth import COGNITO_PROVIDER, cognito_enabled, resolve_token
from frontend.legal import PAGES, OrganisationFacts
from frontend.messages import message_for
from frontend.views import (
    ask,
    connections,
    groups,
    library,
    people,
    relationships,
    reports,
    review,
    upload,
)
from frontend.views import home as home_view
from frontend.views import legal as legal_view
from frontend.views import settings as settings_page

st.set_page_config(page_title="HeritageVoice AI", page_icon="🪔", layout="wide")


def show_status(client: ApiClient) -> None:
    try:
        report = client.ready()
    except ApiError as error:
        st.sidebar.error(message_for(error))
        return
    label = "API ready" if report.ready else "API running, dependencies not ready"
    (st.sidebar.success if report.ready else st.sidebar.warning)(label)


def _page(render: Callable[[ApiClient], None], client: ApiClient, **options: object) -> object:
    return st.Page(lambda: render(client), **options)  # type: ignore[arg-type]


def _legal_pages(facts: OrganisationFacts) -> list[object]:
    """Terms, privacy and the rest. Public: they open without signing in."""
    return [
        st.Page(
            lambda page=page: legal_view.render(page, facts),  # type: ignore[misc]
            title=page.title,
            icon=page.icon,
            url_path=page.slug,
        )
        for page in PAGES
    ]


def _groups_page(client: ApiClient) -> object:
    return _page(
        groups.render,
        client,
        title="Groups and consent",
        icon=":material/groups:",
        url_path="groups",
    )


def _member_sections(client: ApiClient, role: str | None) -> dict[str, list[object]]:
    """Everyone reads the Library and can add a recording; reviewing and settings are admin-only."""
    sections: dict[str, list[object]] = {
        "Explore": [
            _page(
                library.render,
                client,
                title="Library",
                icon=":material/menu_book:",
                url_path="library",
                default=True,
            ),
            _page(ask.render, client, title="Ask", icon=":material/forum:", url_path="ask"),
            _page(
                connections.render,
                client,
                title="Connections",
                icon=":material/hub:",
                url_path="connections",
            ),
        ],
        "Contribute": [
            _page(
                upload.render,
                client,
                title="Add a recording",
                icon=":material/mic:",
                url_path="upload",
            )
        ],
    }
    if role == "reviewer":
        sections["Administration"] = [_groups_page(client)]
    if role == "admin":
        sections["Administration"] = [
            _page(
                review.render,
                client,
                title="Review",
                icon=":material/fact_check:",
                url_path="review",
            ),
            _page(
                reports.render,
                client,
                title="Reports",
                icon=":material/flag:",
                url_path="reports",
            ),
            _page(
                relationships.render,
                client,
                title="Relationships",
                icon=":material/hub:",
                url_path="relationships",
            ),
            _groups_page(client),
            _page(
                people.render, client, title="People", icon=":material/group:", url_path="people"
            ),
            _page(
                settings_page.render,
                client,
                title="Settings",
                icon=":material/tune:",
                url_path="settings",
            ),
        ]
    return sections


def _run_for_visitors(settings: Settings, facts: OrganisationFacts) -> None:
    """No account: the open home page, with sign-in beside the search, and the legal pages."""
    client = ApiClient(settings.api_url, None)
    home = st.Page(
        lambda: home_view.render(client, lambda: st.login(COGNITO_PROVIDER)),
        title="Home",
        icon=":material/home:",
        url_path="home",
        default=True,
    )
    theme.brand()
    explore = _page(
        connections.render,
        client,
        title="Connections",
        icon=":material/hub:",
        url_path="connections",
    )
    st.navigation({"Explore": [home, explore], "Legal": _legal_pages(facts)}).run()


def _run_session_expired(facts: OrganisationFacts) -> None:
    """The API refused the sign-in: say so, and clear the old one. Streamlit still thinks the
    person is signed in, so asking it to sign in again does nothing; signing out starts afresh
    and the home page then offers Sign in."""
    page = st.Page(
        lambda: home_view.render_expired(st.logout),
        title="Sign in",
        icon=":material/login:",
        url_path="signin",
        default=True,
    )
    st.navigation({"Your account": [page], "Legal": _legal_pages(facts)}).run()


def _run_awaiting_approval(settings: Settings, facts: OrganisationFacts) -> None:
    """Signed in, but not approved yet: say so plainly, with sign-out and the legal pages."""
    show_account(None, settings)
    page = st.Page(
        home_view.render_waiting,
        title="Account",
        icon=":material/hourglass_top:",
        url_path="account",
        default=True,
    )
    st.navigation({"Your account": [page], "Legal": _legal_pages(facts)}).run()


def main() -> None:
    theme.apply()
    settings = Settings()
    facts = OrganisationFacts.from_environment(os.environ)
    token = resolve_token(settings, st.user)
    if token is None and cognito_enabled(settings):
        _run_for_visitors(settings, facts)
        return
    client = ApiClient(settings.api_url, token)
    theme.brand()
    show_status(client)
    try:
        role = current_role(client)
    except AwaitingApprovalError:
        _run_awaiting_approval(settings, facts)
        return
    except SessionExpiredError:
        _run_session_expired(facts)
        return
    show_account(role, settings)
    sections = _member_sections(client, role)
    st.navigation({**sections, "Legal": _legal_pages(facts)}).run()


main()
