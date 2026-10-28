# Secrets

Settings and secrets live in a git-ignored `.env` locally. Nothing secret goes in Git, images, Compose files, logs or trace metadata.

| Secret | Rotate how |
| --- | --- |
| `HERITAGEVOICE_DEV_API_TOKEN` | Generate a new long random value (`openssl rand -hex 32`), update `.env`, restart the API. Local development only. |
| `LANGSMITH_API_KEY` | Create a new key in LangSmith, update `.env`, then revoke the old key. |
| LLM provider / AWS keys (when added) | Create a new key at the provider, store it outside Git, then revoke the old key. |

## If a secret was committed or pushed

1. **Rotate it first.** Assume it is already exposed, even if the push is deleted.
2. Remove it from history (`git filter-repo --replace-text` or BFG), then force-push and ask collaborators to re-clone.
3. Check provider logs for use of the old key.
4. Add a rule to `.gitleaks.toml` or `.gitignore` if this kind of secret slipped through.

Terraform plan or state exposed: rotate every value the plan could contain (passwords, keys, tokens), not only the one you noticed.
