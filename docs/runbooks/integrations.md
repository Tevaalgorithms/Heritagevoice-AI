# Keys and services in the admin portal

Settings, then **Keys and services**, lets an admin paste the API keys and settings of the outside
services. Nothing needs the AWS console or a redeploy.

## What can be set

| Service | Values | Used for |
| --- | --- | --- |
| Language models | Anthropic API key (`HERITAGEVOICE_LLM_API_KEY`), OpenAI API key (`OPENAI_API_KEY`), and the key of any catalogue model whose key name ends in `_API_KEY` | Translation, routing, verifying and writing answers. You need at least one. |
| Pinecone | API key, index name, embedding model (default `multilingual-e5-large`), embedding dimension (default 1024) | Meaning-based search |
| LangSmith | API key, project | Tracing (not used by the app yet) |
| Neo4j | Connection address, user name, password | The knowledge graph (not built yet) |

The **Setup checklist** at the top shows which services are ready. For language models one
provider is enough. **Test the Pinecone connection** looks the index up with the saved key (it
writes nothing) and checks the dimension matches.

## How a key is handled

1. The browser sends the key once, over HTTPS, to the admin API. Only admins can.
2. The server writes it to AWS Parameter Store as an encrypted `SecureString` under
   `/heritagevoice/<environment>/<NAME>`, using the site's key, and forgets it.
3. The key is never returned, shown again, logged, put in the database or echoed in an error. The
   page only says *Configured* or *Missing*. The audit log records who set which name, never the value.
4. Servers read keys by name when they need them and keep them in memory for about five minutes.
   Saving a key takes effect within that time. Pinecone settings are picked up the same way, and
   the vector store rebuilds itself when the key, index, model or dimension changes.

Only the names above can be written, and only `ssm:PutParameter` on those names is granted to the
server (`infra/single-instance/iam.tf`, `writable_parameters`). The portal cannot touch the
database password, the cookie secret or the sign-in secret.

Values may use letters, digits and `. _ ~ + / = : @ , -` only, up to 512 characters.

## The trade-off to know about

Before this feature the server could only **read** its secrets. Now it can also **write** a short list
of them, so a stolen admin session could replace an API key (for example with one the attacker
controls). The protections: admin-only, over HTTPS with sign-in and MFA, an allow-list of names, an
audit record of every change, and no ability to read a key back. If you prefer the stricter setup,
remove the `WriteIntegrationSettings` statement and paste keys in the AWS console instead; the
portal then shows *Configured* or *Missing* and saving fails with a clear message.

## First time

1. Merge the change, then run the **infra** workflow for `single-instance` (type the confirmation).
   Until then, saving a key says the server is not allowed to save keys yet.
2. Settings, Keys and services: paste your key, then on the **Models** tab add a model and choose it
   for each job (see `models.md`).
3. For OpenAI: add models with the provider **openai**; the key name defaults to `OPENAI_API_KEY`.
   Put a model from each provider in a job's chain for fail-over across providers.
4. For Pinecone: create the index in the Pinecone console first (its dimension must match), then
   save the key and index name and press the test.

## Notes and limits

- OpenAI support is built and tested without network; it has not been tried with a real OpenAI key.
- Temperature is not sent to OpenAI models (newer ones reject anything but their default).
- Changing the embedding model or dimension needs a new index and re-indexing
  (`python -m app.worker rebuild-index`).
