"""Shell with navigation by role. The API token stays on the Streamlit server."""

import os
from collections.abc import Callable

import streamlit as st

from app.config import Settings
from frontend import theme
from frontend.account import AwaitingApprovalError, SessionExpiredError, current_role
from frontend.api_client import ApiClient, ApiError
from frontend.auth import COGNITO_PROVIDER, cognito_enabled, resolve_token
from frontend.legal import PAGES, LegalPage, OrganisationFacts
from frontend.messages import message_for
from frontend.shell import footer, logo, member_account, visitor_account
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
    """Say so when the API cannot be reached or is not fully ready; stay quiet when it is."""
    try:
        report = client.ready()
    except ApiError as error:
        st.error(message_for(error))
        return
    if not report.ready:
        st.warning("API running, dependencies not ready")


def _page(render: Callable[[ApiClient], None], client: ApiClient, **options: object) -> object:
    return st.Page(lambda: render(client), **options)  # type: ignore[arg-type]


CONTACT = "contact"


def _legal_page(page: LegalPage, facts: OrganisationFacts, in_menu: bool) -> object:
    return st.Page(
        lambda: legal_view.render(page, facts),
        title="Contact" if in_menu else page.title,
        icon=page.icon,
        url_path=page.slug,
        visibility="visible" if in_menu else "hidden",
    )


def _legal_pages(facts: OrganisationFacts, contact_in_menu: bool = False) -> list[object]:
    """Terms, privacy and the rest. Public: they open without signing in. They are in the footer,
    not the menu, except Contact for visitors."""
    return [_legal_page(p, facts, contact_in_menu and p.slug == CONTACT) for p in PAGES]


def _navigate(
    menu: dict[str, list[object]] | list[object], legal: list[object], facts: OrganisationFacts
) -> None:
    """Show the top menu, run the page, then the footer. The legal pages are registered with the
    navigation so their addresses work, but they are hidden from the menu."""
    hidden = [page for page in legal if page.visibility == "hidden"]  # type: ignore[attr-defined]
    if isinstance(menu, dict):
        first = next(iter(menu))
        pages: dict[str, list[object]] | list[object] = {**menu, first: [*menu[first], *hidden]}
    else:
        pages = [*menu, *hidden]
    st.navigation(pages, position="top").run()  # type: ignore[arg-type]
    footer(legal, facts)


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
    """No account: Home, the Library, Connections and Contact, with Sign in at the top right."""
    client = ApiClient(settings.api_url, None)

    def sign_in() -> None:
        st.login(COGNITO_PROVIDER)

    home = st.Page(
        lambda: home_view.render(client, sign_in),
        title="Home",
        icon=":material/home:",
        url_path="home",
        default=True,
    )
    shelf = st.Page(
        lambda: library.render_public(client),
        title="Library",
        icon=":material/menu_book:",
        url_path="library",
    )
    links = _page(
        connections.render,
        client,
        title="Connections",
        icon=":material/hub:",
        url_path="connections",
    )
    legal = _legal_pages(facts, contact_in_menu=True)
    contact = next(page for page in legal if page.visibility == "visible")  # type: ignore[attr-defined]
    logo()
    visitor_account(sign_in)
    _navigate([home, shelf, links, contact], legal, facts)


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
    logo()
    _navigate([page], _legal_pages(facts), facts)


def _run_awaiting_approval(facts: OrganisationFacts) -> None:
    """Signed in, but not approved yet: say so plainly, with sign-out and the legal pages."""
    page = st.Page(
        home_view.render_waiting,
        title="Account",
        icon=":material/hourglass_top:",
        url_path="account",
        default=True,
    )
    logo()
    member_account(None, can_sign_out=True)
    _navigate([page], _legal_pages(facts), facts)


def _run_signed_in(settings: Settings, facts: OrganisationFacts, token: str | None) -> None:
    """Someone with a sign-in: their menu by role, or the page that explains what is missing."""
    client = ApiClient(settings.api_url, token)
    try:
        role = current_role(client)
    except AwaitingApprovalError:
        _run_awaiting_approval(facts)
        return
    except SessionExpiredError:
        _run_session_expired(facts)
        return
    logo()
    member_account(role, can_sign_out=cognito_enabled(settings) and st.user.is_logged_in)
    show_status(client)
    _navigate(_member_sections(client, role), _legal_pages(facts), facts)


def main() -> None:
    theme.apply()
    settings = Settings()
    facts = OrganisationFacts.from_environment(os.environ)
    token = resolve_token(settings, st.user)
    if token is None and cognito_enabled(settings):
        _run_for_visitors(settings, facts)
    else:
        _run_signed_in(settings, facts, token)


main()
