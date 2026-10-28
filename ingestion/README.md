# Ingestion contract

D01 implements deterministic text chunking, access labels, document versions, passage hashes and stable chunk IDs. Repeated ingestion must be idempotent. Missing labels quarantine a document. Do not ingest private material until the live identity and retrieval controls are tested.
