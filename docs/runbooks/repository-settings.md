# Repository settings for maintainers

These settings make the rules in [CONTRIBUTING.md](../../CONTRIBUTING.md) real: **every pull
request needs a maintainer's approval, and every deployment needs a maintainer's approval.** They
are GitHub settings, not code, so a maintainer applies them once (Settings in the repository).
All of them are free for public repositories.

## 1. Approve every pull request

1. **Settings, Rules, Rulesets, New ruleset, Import a ruleset**, and choose
   [`.github/rulesets/main-protection.json`](../../.github/rulesets/main-protection.json). It:
   - blocks direct pushes, force pushes and deletion of `main`;
   - requires a pull request with **one approving review from a code owner**
     ([`.github/CODEOWNERS`](../../.github/CODEOWNERS)), re-requested after every new push, with all
     conversations resolved;
   - requires the checks `checks`, `image`, `secrets`, `terraform` and `workflows` to pass on an
     up-to-date branch.
2. **Solo maintainer note.** GitHub does not let you approve your own pull request, so the ruleset
   lets repository admins bypass *through a pull request* (`bypass_mode: pull_request`). Other
   people's pull requests still need an approval. Remove the `bypass_actors` entry once there is a
   second maintainer, and widen `CODEOWNERS` to a team.
3. **Settings, Actions, General**:
   - Fork pull request workflows: **Require approval for all outside collaborators**.
   - Workflow permissions: **Read repository contents** only; leave "Allow GitHub Actions to
     create and approve pull requests" **off**.

## 2. Approve every deployment

1. **Settings, Environments**. Open `prod` and `infra` (create them if missing) and set:
   - **Required reviewers**: the maintainers who may approve a deployment.
   - **Deployment branches and tags**: `prod` allows `main` and `v*`; `infra` allows `main` only.
   - Leave "Allow administrators to bypass" **off**.
2. Every workflow job that touches AWS declares one of these environments, so it **waits for
   approval before it starts** and before any AWS credential is requested:

   | Workflow | Environment | When it needs your approval |
   | --- | --- | --- |
   | `deploy` | `prod` | after a merge to `main` passes CI, a `v*` tag, or a manual run |
   | `infra` (apply) | `infra` | every apply (also needs the typed stack name) |
   | `secrets`, `first-admin`, `diagnose` | `prod` / `infra` | every run |

3. **The AWS end.** Nothing to change. The CI roles in [`infra/github-oidc`](../../infra/github-oidc)
   only accept a token whose subject is `...:environment:prod` or `...:environment:infra`. GitHub
   issues such a token only to a job that passed the environment's approval, so a job (or a
   forked or modified workflow) that skipped it cannot assume the role. The CI roles also cannot
   change their own permissions.
4. **Test the gate once**: merge a trivial change, open the *deploy* run in the Actions tab, and
   check it shows **Waiting for review** until you approve it.

## 3. Security features

**Settings, Code security**: turn on private vulnerability reporting, Dependabot alerts and
security updates, secret scanning with **push protection**, and CodeQL (default setup). Dependabot
version updates are configured in [`.github/dependabot.yml`](../../.github/dependabot.yml).

## 4. Before making the repository public

- Run the history scan: `gitleaks detect --source . --redact` (CI does this on every change).
- Confirm private working notes are not tracked (`git ls-files docs | grep -v runbooks`), and that
  no key, state file, `*.tfvars`, account ID or personal email is in the files or in history.
- Review the issue and pull request activity of the private period: comments are public too.
- After going public, rotate anything you would not want to have existed in the history.
