# 0007. Build the image in CI and ship it through the releases bucket

**Status:** Accepted

## Context
The server used to build the Docker image itself on every deploy. A change to the dependency lock
(for example a Dependabot bump) reinstalled every package on a small machine that is also serving
the site, and deploys took 10 to 20 minutes against a 20-minute limit. Merging two bumps in a row
meant two such builds. The usual remedy is a registry (for example AWS ECR). Here that needs new
permissions for the CI role, which lives in a stack that is applied by hand, so a wrong order would
break every deploy.

## Decision
CI builds the image in the deploy job, with a layer cache, saves it, and uploads it to the existing
private releases bucket as `releases/<commit>.image.tar.gz` next to the code tarball. `deploy/start.sh`
loads it and starts the stack with `--no-build`. A release that has no shipped image (any made
before this change) is still built on the server, so rolling back keeps working. A damaged image
stops the deploy instead of starting something else.

## Consequences
- A dependency change no longer compiles anything on the production machine; a deploy is a download
  (about 300 MB) and a restart.
- No new AWS resources or permissions: the CI role already writes `releases/*` and the instance
  already reads it. The existing 90-day expiry on `releases/` covers the image files too.
- The `image` check still builds and scans the same Dockerfile at the same commit, but the shipped
  image is a second build of it, not the very same bytes. Shipping the scanned image itself is a
  further step.
- Moving to a registry later is a replacement of the upload and load steps only.

See the [deploy runbook](../runbooks/deploy-single-instance.md).
