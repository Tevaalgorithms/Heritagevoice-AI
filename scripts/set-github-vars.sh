#!/usr/bin/env bash
# Sets the GitHub repository and environment variables that the infra, secrets and deploy
# workflows need. Run it yourself after applying infra/github-oidc, from any directory:
#
#   scripts/set-github-vars.sh
#
# Nothing secret is written: role ARNs and bucket names are configuration, stored as GitHub
# *variables* (not committed to Git). The values are read from AWS and Terraform at run time.
# Create the GitHub environments `infra` and `prod` first (Settings, Environments).
set -euo pipefail

REPO="${REPO:-Tevaalgorithms/Heritagevoice-AI}"
REGION="${REGION:-us-west-2}"
ENVIRONMENT="${ENVIRONMENT:-prod}"
DOMAIN="${DOMAIN:-heritagevoice.tevaalgorithms.com}"
ZONE="${ZONE:-tevaalgorithms.com}"
OIDC_DIR="$(cd "$(dirname "$0")/../infra/github-oidc" && pwd)"

command -v gh >/dev/null || { echo "Install the GitHub CLI (brew install gh) and run: gh auth login" >&2; exit 1; }
command -v terraform >/dev/null || { echo "Install terraform first" >&2; exit 1; }

ACCT="$(aws sts get-caller-identity --query Account --output text)"
STATE_BUCKET="heritagevoice-tfstate-$ACCT"
out() { terraform -chdir="$OIDC_DIR" output -raw "$1"; }

# The Terraform state of github-oidc must be initialised (it was, when you applied it).
plan_role="$(out terraform_plan_role_arn)"
apply_role="$(out terraform_apply_role_arn)"
deploy_role="$(out deploy_role_arn)"

# Keep a Cognito domain prefix you already chose; only generate one the first time.
prefix="$(gh variable get COGNITO_DOMAIN_PREFIX --repo "$REPO" 2>/dev/null || true)"
[[ -n "$prefix" ]] || prefix="hv-$ENVIRONMENT-$(openssl rand -hex 3)"

repo_var() { gh variable set "$1" --repo "$REPO" --body "$2" && echo "repo  $1"; }
env_var() { gh variable set "$2" --repo "$REPO" --env "$1" --body "$3" && echo "$1  $2"; }

repo_var AWS_REGION "$REGION"
repo_var TF_STATE_BUCKET "$STATE_BUCKET"
repo_var TF_ENVIRONMENT "$ENVIRONMENT"
repo_var SITE_DOMAIN "$DOMAIN"
repo_var ROUTE53_ZONE_NAME "$ZONE"
repo_var COGNITO_DOMAIN_PREFIX "$prefix"
# Budget alert: only set when BUDGET_EMAIL is given (an unset variable skips the alert).
[[ -z "${BUDGET_EMAIL:-}" ]] || repo_var TF_BUDGET_EMAIL "$BUDGET_EMAIL"
repo_var AWS_TF_PLAN_ROLE_ARN "$plan_role"

env_var infra AWS_TF_APPLY_ROLE_ARN "$apply_role"

env_var "$ENVIRONMENT" AWS_DEPLOY_ROLE_ARN "$deploy_role"
env_var "$ENVIRONMENT" AWS_REGION "$REGION"
env_var "$ENVIRONMENT" SITE_DOMAIN "$DOMAIN"
env_var "$ENVIRONMENT" RELEASES_BUCKET "heritagevoice-$ENVIRONMENT-releases-$ACCT"

echo
echo "Still to set after the first workflow runs:"
echo "  repo variable        COGNITO_USER_POOL_ID, COGNITO_APP_CLIENT_ID   (infra -> cognito)"
echo "  $ENVIRONMENT variable  INSTANCE_ID                                   (infra -> single-instance)"
