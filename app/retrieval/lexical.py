"""Keyword search over indexed chunks, limited to the caller's communities.

On PostgreSQL this is full-text search with the 'simple' configuration (no stemming or stop
words, so exact local terms and Tamil words match). Query words become exact OR-ed lexemes, so a
natural-language question finds any chunk that shares a word. On other databases (local SQLite,
unit tests) a small BM25 scorer gives the same shape of result. The caller must still pass the
IDs through `eligibility`; this only narrows candidates.
"""

import math
from collections import Counter

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.db.repositories import ChunkRepository
from app.retrieval.tokenize import tokens

K1 = 1.5
B = 0.75

POSTGRES_QUERY = text(
    """
    WITH q AS (
        SELECT (
            SELECT string_agg(quote_literal(word), ' | ')
            FROM unnest(tsvector_to_array(to_tsvector('simple', :query))) AS word
        )::tsquery AS tsq
    )
    SELECT evidence_id
    FROM evidence_chunk, q
    WHERE community_id IN :communities AND to_tsvector('simple', text) @@ q.tsq
    ORDER BY ts_rank(to_tsvector('simple', text), q.tsq) DESC, evidence_id
    LIMIT :limit
    """
).bindparams(bindparam("communities", expanding=True))


def _document_frequency(docs: dict[str, list[str]]) -> Counter[str]:
    return Counter(word for words in docs.values() for word in set(words))


def _mean_length(lengths: dict[str, int]) -> float:
    return max(sum(lengths.values()) / max(len(lengths), 1), 1.0)


class _Corpus:
    """Word statistics for a set of documents, enough to score them with BM25."""

    def __init__(self, docs: dict[str, list[str]]) -> None:
        self._counts = {doc_id: Counter(words) for doc_id, words in docs.items()}
        self._lengths = {doc_id: len(words) for doc_id, words in docs.items()}
        self._average = _mean_length(self._lengths)
        self._frequency = _document_frequency(docs)

    def _idf(self, word: str) -> float:
        frequency = self._frequency[word]
        return math.log(1 + (len(self._counts) - frequency + 0.5) / (frequency + 0.5))

    def _term(self, word: str, doc_id: str) -> float:
        count = self._counts[doc_id][word]
        if count == 0:
            return 0.0
        length = self._lengths[doc_id]
        norm = count * (K1 + 1) / (count + K1 * (1 - B + B * length / self._average))
        return self._idf(word) * norm

    def ranking(self, words: set[str]) -> list[str]:
        scores = {d: sum(self._term(w, d) for w in words) for d in self._counts}
        matching = [d for d, score in scores.items() if score > 0]
        return sorted(matching, key=lambda d: (-scores[d], d))


def bm25_ranking(query_tokens: list[str], docs: dict[str, list[str]]) -> list[str]:
    """Document IDs that share a query word, best first (ties by ID for a stable order)."""
    if not docs or not query_tokens:
        return []
    return _Corpus(docs).ranking(set(query_tokens))


def _portable(session: Session, query: str, communities: frozenset[str], limit: int) -> list[str]:
    chunks = ChunkRepository(session).for_communities(communities)
    docs = {chunk.evidence_id: tokens(chunk.text) for chunk in chunks}
    return bm25_ranking(tokens(query), docs)[:limit]


def _postgres(session: Session, query: str, communities: frozenset[str], limit: int) -> list[str]:
    rows = session.execute(
        POSTGRES_QUERY, {"query": query, "communities": sorted(communities), "limit": limit}
    )
    return [row[0] for row in rows]


def lexical_search(
    session: Session, query: str, communities: frozenset[str], limit: int = 20
) -> list[str]:
    """Candidate chunk IDs for the query, best first. Empty without communities or query words."""
    if not communities or not tokens(query):
        return []
    search = _postgres if session.get_bind().dialect.name == "postgresql" else _portable
    return search(session, query, communities, limit)
