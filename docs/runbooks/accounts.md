# Accounts: sign-up, approval and administrators

## How people get in

| Who | How |
| --- | --- |
| Anyone | Searches and reads public recordings from the home page. No account. |
| Contributor | Creates an account (Sign up on the Cognito page, confirms their email), then **an administrator approves it** in **People → Waiting for approval** and picks the communities they may add recordings to. Then they sign in and upload. |
| Administrator | Only ever **invited by another administrator** in **People → Invite** (role Administrator). A sign-up can never become an administrator: approval only creates the contributor role. |

Until approved, a new account can sign in but the server answers 403 to everything, so the app
shows "Your account is waiting for approval". Every approval and decline is written to the audit log.

## What the admin sees

The waiting list comes from Cognito (confirmed, enabled, email verified) minus everyone who already
has a record in the app. Declining disables the Cognito account and signs it out. It does not
delete it.

## Setting up

1. Apply the `cognito` stack in the `infra` workflow (turns self sign-up on).
2. Apply the `single-instance` stack (lets the server list Cognito users).
3. The first administrator is still created with the `first-admin` workflow.

## Abuse

Sign-up is open, so expect junk accounts. They are harmless (denied everywhere, and only
email-verified ones appear in the list), but they count toward Cognito's monthly active users.
If it becomes a nuisance, put AWS WAF with a CAPTCHA in front of the sign-in domain.
