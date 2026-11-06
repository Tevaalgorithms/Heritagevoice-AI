# A sign-in page on your own domain

By default the hosted sign-in and sign-up pages are on Amazon's domain
(`hv-prod-xxxxxx.auth.us-west-2.amazoncognito.com`). A custom domain such as
`login.heritagevoice.org` puts them under your name, which people trust more. **Sign in and Sign up
are the same Cognito pages, so both move together.**

The application and everything else stay in Oregon. Only the certificate for the sign-in domain is
created in N. Virginia (`us-east-1`), because Cognito serves custom domains through CloudFront and
CloudFront accepts certificates from nowhere else. It is free and renews by itself.

## What it needs

- A **parent domain that already resolves**: `heritagevoice.org` has its A record. Cognito checks
  this before it accepts `login.heritagevoice.org`.
- The GitHub repository variable **`LOGIN_DOMAIN`** = `login.heritagevoice.org`.
  (`ROUTE53_ZONE_NAME` is already `heritagevoice.org`.) Leave `LOGIN_DOMAIN` empty to keep Amazon's.

## Switching on

1. Merge the pull request and approve its deploy. The only change in the deploy is the sign-out
   rule in Caddy, which now also recognises `login.<domain>`.
2. Set the repository variable `LOGIN_DOMAIN` (Settings → Secrets and variables → Actions →
   Variables).
3. **Actions → infra → Run workflow**: stack `cognito`, confirm `cognito`, approve `infra`.
   It creates the certificate and its DNS proof, then **replaces the pool's domain** and adds the
   `login.` record. **Sign-in is unavailable for about 5 to 15 minutes**: Cognito builds a
   CloudFront distribution for the new domain. If the run fails on that step, run it again.

## Checks

- `dig +short login.heritagevoice.org` answers.
- On the site, **Sign in** goes to `https://login.heritagevoice.org/login?…` with a padlock, and
  **Sign up** is on the same address.
- Sign-out returns to the home page.
- Streamlit finds the new address through Cognito's discovery document. Check it names the custom
  domain:
  `curl -s https://cognito-idp.us-west-2.amazonaws.com/<user pool id>/.well-known/openid-configuration`
  and look at `authorization_endpoint`.

## Going back

Clear the `LOGIN_DOMAIN` variable and run the infra workflow for `cognito` again. The pool returns
to Amazon's domain (after the same few minutes). The certificate and records are removed.

## Things to know

- A pool has one domain at a time, which is why switching has a short outage.
- The page's colours and logo are kept: the customisation is re-applied after the domain changes.
- The standard Cognito page cannot hold a custom "back to site" link; the browser's back button
  works.
