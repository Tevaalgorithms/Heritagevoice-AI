# Models, keys and fall-backs

Admins manage models in the app (Settings page, admin role). Nothing here needs a deploy.

## How it fits together

- **Catalogue** (database table `model_catalog`): the models an admin has approved. Each entry has
  a provider, a status and the **name** of the key it uses. The key value is never stored here.
- **Statuses:** *active* (can be chosen), *deprecated* (keeps working where already chosen, cannot
  be newly chosen), *disabled* (serves nothing; a job moves on to its next fall-back).
- **Per job** (database table `model_setting`): a primary model, up to three fall-backs in order,
  and temperature, timeout and retries. Today the only job is translation.
- **Keys** live in AWS Systems Manager Parameter Store as `SecureString`, under the site's path
  (for example `/heritagevoice/prod/HERITAGEVOICE_LLM_API_KEY`). The server reads a key by name when
  it needs it and keeps it in memory for about five minutes, so adding or rotating a key takes
  effect without a restart or a deploy. If Parameter Store cannot be read, an environment variable
  of the same name is used (this is how local development works).

## What happens when a model fails

For each call the server tries the primary model, then each fall-back in order. A model is skipped
if its key is missing, and abandoned for that call if the provider times out, rate-limits, is
overloaded, rejects the key, or returns output that does not match. If every model fails, the call
fails with the safe code `mt`: ingestion keeps the transcript and records that the translation is
missing. The log says which model served a call when it was not the primary.

## Common tasks

- **Add a key:** Parameter Store, Create parameter, name `/heritagevoice/prod/<KEY_NAME>`, type
  SecureString, KMS key `alias/heritagevoice-prod`. Values may use letters, digits and
  `. _ ~ + / = : @ , -` only. The Settings page shows *Configured* within a few minutes.
- **Add a model:** Settings, *Add a model*: the model name exactly as the provider names it, the
  provider, and the key name. Then pick it as a primary or fall-back for a job and Save.
- **Retire a model:** set it to *deprecated* (stops new choices) or *disabled* (stops serving).
- **Use a second provider's key:** give that model its own key name, for example
  `OTHER_PROVIDER_API_KEY`, and store that parameter. Only the providers listed in the code can be
  chosen (today `anthropic`); a new provider needs a small adapter before it can serve calls.
- **Rotate a key:** overwrite the parameter. Nothing else is needed.

## Limits and notes

- Keys are never shown, returned by the API, logged or stored in the database. The Settings page
  only says whether a key is configured.
- Adding a catalogue entry records its key name in the audit log, never a value.
- The *Test* button sends one tiny request (costs a few tokens) with the primary model and its key.
- The instance role already allows reading parameters under the site's path; no infrastructure
  change is needed to add a key.
