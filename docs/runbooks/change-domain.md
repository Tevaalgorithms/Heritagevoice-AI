# Moving the site to a new domain

The site's address lives in four places. Changing it needs all four, in this order, because
sign-in only works when the address the browser uses is also on Cognito's allowed list.

| Where | What it controls | Changed by |
|---|---|---|
| Route 53 | The DNS record that points the name at the server | `infra` workflow, stack `single-instance` |
| Cognito | The sign-in return address (callback and logout URLs) | `infra` workflow, stack `cognito` |
| Parameter Store `HV_DOMAIN` | The address Caddy gets a certificate for, and Streamlit's `redirect_uri` | AWS Console, then a deploy |
| GitHub variables `SITE_DOMAIN`, `ROUTE53_ZONE_NAME` | What the workflows above and the deploy health check use | GitHub settings |

Caddy gets a free HTTPS certificate for the new name by itself once DNS points at the server.
CloudFront is not needed: it is for static sites and would complicate Streamlit's websockets and
sign-in cookies.

## Before you start

1. Register the domain: AWS Console → Route 53 → **Registered domains → Register domain**. Turn on
   **privacy protection** and **auto-renew**.
2. Click the **verification link** AWS emails to the registrant contact within 15 days, or the
   domain is suspended.
3. Wait until the domain shows **Registered** and a **hosted zone** for it exists (Route 53 →
   Hosted zones). Registering through Route 53 creates the zone for you.
4. Pick a quiet time. Between steps 5 and 8 the site is unavailable for about 10 to 15 minutes.

## The switch

1. **Parameter Store** (AWS Console → Systems Manager → Parameter Store, region us-west-2): create
   `/heritagevoice/prod/HV_DOMAIN`, type **String**, value the new domain (for example
   `heritagevoice.org`). Nothing changes until the deploy in step 8.
2. **GitHub → Settings → Secrets and variables → Actions → Variables**: set the repository
   variables `SITE_DOMAIN` (new domain) and `ROUTE53_ZONE_NAME` (the new domain, which is its own
   zone).
3. **GitHub → Settings → Environments → prod**: set its variable `SITE_DOMAIN` to the new domain.
   The deploy's health check uses this one.
4. Check DNS is ready: the new zone exists (see above).
5. **Actions → infra → Run workflow**: stack `cognito`, confirm `cognito`, approve `infra`. Sign-in
   at the old address stops working from here.
6. **Actions → infra → Run workflow**: stack `single-instance`, confirm `single-instance`, approve
   `infra`. This adds the new name's record and removes the old one.
7. Wait until the name resolves to the server's address:
   `dig +short heritagevoice.org` (use your domain) shows the Elastic IP.
8. **Actions → deploy → Run workflow** on `main` (or re-run the latest deploy) and approve `prod`.
   The deploy re-reads Parameter Store, so the new `HV_DOMAIN` replaces the old one, and Caddy
   fetches the certificate.

## `www.`

When the site is at the top of its own domain (for example `heritagevoice.org`), the `single-instance`
stack also adds a `www.` record, and Caddy redirects `www.<domain>` to `<domain>` with a
permanent redirect, so there is one official address. A domain that is a subdomain of another gets no
`www.` record. After changing the infrastructure, run the deploy once more so Caddy asks for the
`www.` certificate.

## Check

- `https://<new domain>/` loads with a padlock, and signing in and out works.
- The Library, Ask and an admin page load.
- `https://www.<new domain>/` redirects to `https://<new domain>/` (domains at the top level only).
- The old address no longer answers (expected).

## Afterwards

- Update the "live at" links in the README and any place that names the old address.
- Set the contact email on the legal pages only if you decide to publish one
  (see `docs/runbooks/secrets.md`).

## If something goes wrong

- **Sign-in loops or "redirect mismatch":** step 5 did not finish, or `SITE_DOMAIN` was wrong when
  it ran. Fix the variable and run `cognito` again.
- **Certificate error:** DNS did not resolve yet when Caddy asked. Wait for DNS (step 7), then run
  the deploy again.
- **Go back:** set the variables and `HV_DOMAIN` to the old values and repeat steps 5, 6 and 8.
