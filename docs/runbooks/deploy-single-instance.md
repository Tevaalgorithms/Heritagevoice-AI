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

Status: the Terraform validates and the container stack was tested locally, but **none of this
has been applied to a real AWS account yet**. Expect to fix small things on the first run and
record them here.

## What you need

- An AWS account with MFA, the AWS CLI configured, and Terraform 1.6 or newer.
- A domain you control. This guide uses `heritagevoice.tevaalgorithms.com`, a subdomain of an
  existing Route 53 zone, so the main site is untouched; Terraform adds one `A` record only.
- Check the zone has no `CAA` record that blocks Let's Encrypt (`letsencrypt.org`).
- This repository's URL (it must be reachable by the instance: public, or add a deploy key).

## 1. Remote state (once)

Create an encrypted, versioned S3 bucket for Terraform state and add a `backend "s3"` block to
`versions.tf` in both stacks. Never commit state, plans or `*.tfvars` (`AGENTS.md`).

## 2. Cognito (sign-in)

```sh
cd infra/cognito
terraform init
terraform apply \
  -var region=<region> -var environment=demo -var domain_prefix=<unique-prefix> \
  -var 'callback_urls=["https://<domain>/oauth2callback"]' \
  -var 'logout_urls=["https://<domain>/"]'
```

Note the outputs `user_pool_id` and `app_client_id`. Copy the app client **secret** from the
Cognito console (it is intentionally not a Terraform output).

## 3. The instance

Create `infra/single-instance/demo.tfvars` (git-ignored):

```hcl
region                = "us-west-2"
environment           = "demo"
domain                = "heritagevoice.tevaalgorithms.com"
route53_zone_name     = "tevaalgorithms.com"   # optional: Terraform adds only the A record
repo_url              = "https://github.com/Tevaalgorithms/Heritagevoice-AI.git"
repo_ref              = "main"                 # use a release tag when sharing
cognito_user_pool_id  = "<from step 2>"
cognito_app_client_id = "<from step 2>"
budget_email          = "<your email>"
```

(`demo.tfvars.example` has the same content. Terraform looks the zone up by name, so no zone ID
is needed.)

```sh
cd infra/single-instance
terraform init
terraform plan -var-file=demo.tfvars     # review locally; do not paste the output anywhere
terraform apply -var-file=demo.tfvars
```

The instance boots, installs Docker, mounts its data disk, fetches the code and writes the
non-secret settings. **It does not start the app yet**, because the secrets do not exist.

## 4. DNS

Skipped when `route53_zone_name` is set: Terraform creates the `A` record. Otherwise point the
domain's `A` record at the `public_ip` output.
Caddy needs this to get a certificate. No domain yet? A name such as `1-2-3-4.nip.io` (your IP
with dashes) also works for a demo.

## 5. Secrets (SSM Parameter Store)

Create these as `SecureString`, encrypted with the stack's key, under the path from the
`ssm_parameter_path` output (`/heritagevoice/demo`). Values may use letters, digits and
`. _ ~ + / = : @ , -` only.

```sh
put() { aws ssm put-parameter --region <region> --type SecureString --overwrite \
  --key-id alias/heritagevoice-demo --name "/heritagevoice/demo/$1" --value "$2" >/dev/null; }

put POSTGRES_PASSWORD "$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
put HV_COOKIE_SECRET  "$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
put HV_COGNITO_CLIENT_SECRET "<app client secret from the console>"
```

## 6. Start the app

```sh
aws ssm start-session --target <instance_id> --region <region>      # the session_command output
sudo /opt/heritagevoice/deploy/start.sh
```

This renders the configuration from the parameters, builds the image (tagged with the Git
commit), runs the database migrations and starts everything. Check it:

```sh
curl -i https://<domain>/health
curl -i https://<domain>/ready        # 200 once PostgreSQL and the bucket are reachable
```

## 7. First admin

1. In the Cognito console, invite yourself, then add the user to the `admin` group.
2. Copy the user's `sub`, then on the instance:

   ```sh
   cd /opt/heritagevoice
   sudo docker compose --env-file /etc/heritagevoice/app.env -f deploy/docker-compose.yml \
     exec api python -m app.bootstrap --sub <sub>
   ```

3. Sign in at `https://<domain>`. Further users are invited through the admin API.
4. Uploads also need a consent record for each community. There is no endpoint for that yet
   (TODO task 2.8); until it exists, create one from a short script run the same way.

## Deploy from GitHub Actions (CI/CD)

After the first manual start, releases go out from GitHub. The workflow
`.github/workflows/deploy.yml` signs in to AWS with OpenID Connect (no access keys), then runs
`deploy/start.sh <tag>` on the instance through Systems Manager and smoke-tests `/ready`. It
needs the reviewer's approval, refuses to deploy a commit whose CI checks are not all green, and
only accepts a Git ref made of letters, digits and `. _ / -`.

One-time setup:

1. Create the deploy role (needs the instance ID from step 3):

   ```sh
   cd infra/github-oidc
   terraform init
   terraform apply -var region=us-west-2 -var environment=demo \
     -var github_repo=Tevaalgorithms/Heritagevoice-AI -var instance_id=<instance_id>
   # add -var create_oidc_provider=false if the account already has the GitHub OIDC provider
   ```

2. In GitHub: Settings, Environments, New environment `demo`. Add yourself as a **required
   reviewer** and restrict deployments to the `main` branch and `v*` tags. The role trusts only
   this environment of this repository.
3. Add the environment variables (they are not secrets, but keep them out of Git):

   ```sh
   gh variable set AWS_DEPLOY_ROLE_ARN --env demo --body "<deploy_role_arn output>"
   gh variable set AWS_REGION --env demo --body us-west-2
   gh variable set INSTANCE_ID --env demo --body "<instance_id>"
   gh variable set SITE_DOMAIN --env demo --body heritagevoice.tevaalgorithms.com
   ```

Releasing: `git tag v0.1.0 && git push origin v0.1.0` (or Actions, deploy, Run workflow with a
tag or branch). Approve the run; it deploys and smoke-tests. **Rolling back** is the same
workflow with the previous tag.

Why `terraform apply` is not in CI: this repository is public, so workflow logs are public, and
apply output shows account details. Infrastructure changes are applied from your own machine
(`terraform plan` locally first); CI only checks `fmt` and `validate`. Secrets are rotated by
hand in SSM, then re-run the deploy.

## Update, roll back, stop, tear down

- **Update or roll back** (manual alternative to the workflow):
  `sudo /opt/heritagevoice/deploy/start.sh <tag-or-branch>`; roll back with the previous tag.
- **Stop between demos:** `aws ec2 stop-instances --instance-ids <id>`. You still pay for the
  disks, the public IP and the key (about $8 a month). Start it again with `start-instances`;
  the containers restart on their own.
- **Tear down:** `terraform destroy -var-file=demo.tfvars`. The audio bucket is versioned and
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

- No failover, no point-in-time recovery, no autoscaling.
- The deploy workflow passes `actionlint` but has never run; the OIDC role has never been assumed.
- Not yet verified against real AWS: the Transcribe and S3 adapters, the Cognito admin adapter,
  the Streamlit Cognito login, the DLM snapshot policy with the customer key, and the first-boot
  script on a real instance.
