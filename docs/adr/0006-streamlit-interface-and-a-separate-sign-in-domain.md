# 0006. Streamlit for the interface; Cognito on its own sign-in domain

**Status:** Accepted

## Context
The team is small and the interface has many pages (library, ask, review, groups, settings). It must
be usable by non-technical elders' families, and sign-in must be trustworthy.

## Decision
The interface is Streamlit, calling the API with the signed-in user's token; it holds no business
rules. Sign-in is Amazon Cognito (with multi-factor authentication) on its own domain,
`login.heritagevoice.org`, so people enter their password on a page that is clearly ours and no
password is ever handled by the application. The top menu changes by role (visitor, contributor,
coordinator, administrator), but the server still decides what each role may do.

## Consequences
- Fast to build and change; Streamlit limits fine layout control, so a few pages use custom CSS.
- Sessions follow Cognito token lifetimes (30 minutes); an expired session shows a clear page and a
  way back in.
- Moving the site to another domain is a documented procedure (see the change-domain runbook).

See the [login domain runbook](../runbooks/login-domain.md).
