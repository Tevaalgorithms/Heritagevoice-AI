# Deploy the MVP on one small AWS instance

A low-cost profile for development and demos: one `t4g.small` instance runs Caddy (automatic
HTTPS), the UI, the API, the worker and PostgreSQL in containers. AWS services are used through
the instance role, so there are **no long-lived AWS keys anywhere**.

Rough cost in `us-west-2` (Oregon): about **$21-23 a month** while running (instance $12.3, disks
$3.2, public IPv4 $3.7, KMS $1, snapshots $1; S3, SSM and Session Manager are about free), and
about $9 while the instance is stopped. Transcribe adds about $0.024 per audio minute. Verify
current prices before relying on this.

> **Use synthetic or explicitly approved data only.** One server has no failover and backups are
> daily disk snapshots, not point-in-time recovery. Move to a managed setup (RDS, load balancer,
> containers) before real community recordings go in.

Status: this profile has been applied and runs the live site at <https://heritagevoice.org>, deployed
by the workflows below. Names in this guide (`example.org`, `<owner>/<repo>`, `<account>`) are
placeholders for your own values.

## What you need

- An AWS account with MFA, the AWS CLI configured, and Terraform 1.6 or newer.
- A domain you control. This guide uses `heritagevoice.example.org`, a subdomain of an existing
  Route 53 zone, so the main site is untouched; Terraform adds one `A` record only.
- Check the zone has no `CAA` record that blocks Let's Encrypt (`letsencrypt.org`).
- This repository's URL (it must be reachable by the instance: public, or add a deploy key).

## Everything runs through CI/CD

Nothing is created or deployed from a laptop, except the one-time bootstrap below. Secrets are never
printed or passed through Terraform, and workflow logs never contain them.

| Workflow | What it does | Confirmation |
| --- | --- | --- |
| `infra` | Pull request: read-only `terraform plan`. Manual run on `main`: apply `cognito` or `single-instance` | type the stack name |
| `secrets` | Creates the generated secrets in Parameter Store (never overwrites) | type `create-secrets` |
| `deploy` | Packs the code, uploads it to the private releases bucket, runs it on the instance, smoke-tests `/ready` | type `deploy` |

## One-time bootstrap (by a person, because it defines what CI may do)

1. **State bucket**: a private, versioned, encrypted S3 bucket named `heritagevoice-tfstate-<account>`
   (create it once per account). Never put the account ID in Git.
2. **CI roles** (`infra/github-oidc`):

   ```sh
   cd infra/github-oidc
   terraform init -backend-config="bucket=<state bucket>" -backend-config="region=us-west-2"
   terraform apply -var region=us-west-2 -var environment=prod \
     -var github_repo=<owner>/<repo> -var instance_id=<see below> \
     -var releases_bucket=heritagevoice-prod-releases-<account> -var state_bucket=<state bucket> \
     -var create_oidc_provider=false \
     -var github_subject_prefix="$(gh api repos/<owner>/<repo>/actions/oidc/customization/sub --jq .sub_claim_prefix)"
   # create_oidc_provider=false: the account already has the GitHub OIDC provider
   ```

   `instance_id` does not exist before the first `infra` run. Apply this stack twice: first with
   a placeholder such as `i-00000000000000000`, then again with the real ID after step 4.
3. **GitHub settings**
   - Environment `infra`: deployments from `main` only, **required reviewers** (see below).
     Variable `AWS_TF_APPLY_ROLE_ARN` = output `terraform_apply_role_arn`.
   - Environment `prod`: `main` and `v*` tags only, **required reviewers** (see below). Variables
     `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `INSTANCE_ID`, `SITE_DOMAIN`, `RELEASES_BUCKET`.
   - Repository variables: `AWS_REGION`, `TF_STATE_BUCKET`, `TF_ENVIRONMENT` (`prod`),
     `SITE_DOMAIN`, `ROUTE53_ZONE_NAME`, `COGNITO_DOMAIN_PREFIX` (unique, e.g. `hv-prod-<6 hex>`),
     `TF_BUDGET_EMAIL` (empty to skip the alert), `AWS_TF_PLAN_ROLE_ARN`, and after step 4
     `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`.
   - Branch protection on `main` and the `CODEOWNERS` file: see
     [`repository-settings.md`](repository-settings.md).

## Approval gates

Two independent gates stand between a pull request and your AWS account:

1. **GitHub.** Every job that touches AWS (`deploy`, `infra` apply, `secrets`, `first-admin`,
   `diagnose`) runs in the GitHub environment `prod` or `infra`. Give those environments
   **required reviewers**: the job then waits, and only starts after a maintainer approves it.
   Merging a pull request into `main` triggers the deploy, but nothing reaches AWS until the
   approval is given.
2. **AWS.** The CI roles (`infra/github-oidc`) trust only tokens issued to a job running in the
   named environment (`...:environment:prod` or `...:environment:infra`). A job that never passed
   the environment's approval cannot obtain AWS credentials, whatever the workflow file says.

Applies and secrets also need a typed confirmation. Pull requests from forks never receive AWS
credentials. See [`repository-settings.md`](repository-settings.md) for the exact settings.

## Order of the first run

1. Run `infra` with `cognito`. Copy `user_pool_id` and `app_client_id` from the log into the
   repository variables `COGNITO_USER_POOL_ID` and `COGNITO_APP_CLIENT_ID`.
2. Run `infra` with `single-instance`. Copy `instance_id` into the `prod` variable `INSTANCE_ID`
   and into the second `github-oidc` apply; copy `releases_bucket` into `RELEASES_BUCKET`.
3. Run `secrets`. It creates `POSTGRES_PASSWORD`, `HV_COOKIE_SECRET` and
   `HV_COGNITO_CLIENT_SECRET` directly in Parameter Store. Terraform never sees the values, so
   they are not in state or plans.
4. Add the provider keys yourself in the Parameter Store console as `SecureString` under
   `/heritagevoice/prod/` (LLM key, `PINECONE_API_KEY`, `PINECONE_INDEX`).
   **Releases are automatic.** After each deploy that follows a merge to `main`, the `tag` job
   tags the live commit with the next patch version (`v0.1.3` becomes `v0.1.4`) and creates a GitHub
   Release listing every PR merged since the last one. For a bigger jump (`v0.2.0`), push that tag
   yourself; the next automatic tag continues from it. A commit that already has a tag is skipped.
5. The first deploy happens when the CI checks pass on `main` (or push a `v*` tag, or run `deploy` and type `deploy`).
6. Check `https://<domain>/health` and `/ready`.

Values in Parameter Store may use letters, digits and `. _ ~ + / = : @ , -` only.

Rules that keep secrets out of Terraform: no `aws_ssm_parameter` resource with a value, no
`random_password`, no secret `variable`, no `TF_VAR_*` secret. The repository scan test checks
the first two.

## 7. First admin

1. In the Cognito console, invite yourself, then add the user to the `admin` group.
2. Copy the user's `sub`, then on the instance:

   ```sh
   cd /opt/heritagevoice
   sudo docker compose --env-file /etc/heritagevoice/app.env -f deploy/docker-compose.yml \
     exec api python -m app.bootstrap --sub <sub>
   ```

3. Sign in at `https://<domain>`. Further users are invited through the admin API.
4. Uploads need a consent: in the app, an administrator or coordinator creates a group and records
   its consent under **Groups and consent**; contributors can also share openly and give their own
   consent on the upload form.

## Releasing and rolling back

Actions, deploy, Run workflow with a tag or branch, and type `deploy`. Each run uploads
`releases/<commit>.tar.gz`, builds the image in CI and uploads it as
`releases/<commit>.image.tar.gz`, then runs `hv-deploy <commit>` on the instance, which loads that
image (nothing is built on the server). **Rolling back** is the same workflow on the previous tag;
a release made before images were shipped has none, so the server builds it as it used to. The workflow refuses a commit whose CI checks are not
all green and accepts only refs made of letters, digits and `. _ / -`.

## Update, roll back, stop, tear down

- **Update or roll back:** run the `deploy` workflow (previous tag to roll back).
- **Stop between demos:** `aws ec2 stop-instances --instance-ids <id>`. You still pay for the
  disks, the public IP and the key (about $8 a month). Start it again with `start-instances`;
  the containers restart on their own.
- **Tear down:** destroy through a reviewed change; the Cognito pool has deletion protection on. The audio bucket is versioned and
  not force-destroyed, so empty it deliberately first. Delete the SSM parameters yourself.

## Security notes

- Only ports 80 and 443 are open; there is no SSH (use Session Manager).
- Containers run read-only, as a non-root user, with all Linux capabilities dropped.
- Secrets live in SSM and in two root-only files on the instance; none are in Git, the image
  or Terraform state.
- The instance metadata hop limit is 2 so containers can reach the role credentials. Every
  container on the host can therefore use the instance role; keep the host single-purpose.
- `/docs` and `/openapi.json` are not exposed; the API answers only on the listed paths.

## Known gaps (things this profile does not do)

- No failover, no point-in-time recovery, no autoscaling. Backups are daily disk snapshots, kept for
  7 days.
- A restore from a snapshot has not been rehearsed. Do one before relying on the backups.
- Transcription quality has not been measured per language; see the languages guide.

What has run for real on the live site: the deploy and infrastructure workflows (through the OIDC
roles), the Transcribe and S3 adapters, Cognito sign-in on its own domain, and the first-admin
workflow.

## The sign-in page

The page where people type their email and password is hosted by Cognito, not by this app. Its look
comes from `infra/cognito/branding/` (`logo.png` under 100 KB, `hosted-ui.css` under 3 KB), applied
by the `infra` workflow (`cognito` stack). Cognito's classic page only accepts the classes already
in that stylesheet and ignores anything else; the wording ("Sign in with your email and password")
and layout cannot be changed with this version. A fully custom page needs Cognito's newer managed
login. To change the colours or logo, edit those two files and run the `infra` workflow again.

## Signing out

The Sign out button ends the app session and the Cognito session, then returns to the home page.
Streamlit sends the browser to Cognito's `/logout` address with the standard OpenID parameters,
but Cognito requires `logout_uri` and otherwise shows "Required parameters missing". The Caddyfile
adds `logout_uri` (this site's home page) to that one redirect. The home page must be in the app
client's allowed sign-out URLs (the `logout_urls` setting of `infra/cognito`, already
`https://<domain>/`). If sign-out ever shows a Cognito error again, check that value first.
