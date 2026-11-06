# Architecture decision records

Short notes on the decisions that shape HeritageVoice, and why. Each is one page: the situation, what
was decided, and what it costs. To change a decision, add a new record that supersedes the old one
instead of rewriting history.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-postgresql-is-the-source-of-truth.md) | PostgreSQL is the source of truth; Pinecone and Neo4j are rebuildable copies | Accepted |
| [0002](0002-access-is-default-deny-and-decided-on-the-server.md) | Access is default-deny and decided on the server | Accepted |
| [0003](0003-the-knowledge-graph-is-reviewed-by-people.md) | The knowledge graph is reviewed by people | Accepted |
| [0004](0004-answers-are-built-from-verified-claims.md) | Answers are built from verified claims, with citations added by code | Accepted |
| [0005](0005-one-small-instance-deployed-only-by-ci.md) | One small AWS instance, deployed only by CI/CD | Accepted |
| [0006](0006-streamlit-interface-and-a-separate-sign-in-domain.md) | Streamlit for the interface; Cognito on its own sign-in domain | Accepted |

Template: copy any record and keep the headings *Context*, *Decision*, *Consequences*.
