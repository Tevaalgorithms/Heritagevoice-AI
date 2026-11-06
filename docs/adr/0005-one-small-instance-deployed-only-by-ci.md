# 0005. One small AWS instance, deployed only by CI/CD

**Status:** Accepted

## Context
The project starts with a handful of communities and little money. A multi-service, multi-zone
platform would cost more to run and to understand than it earns at this stage.

## Decision
Everything runs on one small EC2 instance in us-west-2 (containers for the API, worker, interface and
Caddy; PostgreSQL on the instance, backed up by daily encrypted disk snapshots). Infrastructure is Terraform. Nothing is
deployed or applied from a laptop: GitHub Actions does it with short-lived OIDC credentials, and a
maintainer must approve the `infra` and `prod` environments. Secrets live in AWS Parameter Store.

## Consequences
- Cheap and simple; one machine is a single point of failure and backups are daily snapshots, not point-in-time recovery, so a restore drill matters.
- Deploys are reviewed and repeatable, and no AWS keys are stored in GitHub.
- Growing later (managed database, more instances) is a new record, not a rewrite.

See the [deploy runbook](../runbooks/deploy-single-instance.md).
