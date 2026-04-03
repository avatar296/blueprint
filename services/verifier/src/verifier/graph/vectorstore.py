"""pgvector-backed entity matching for KYB discovery.

Stores company name embeddings in PostgreSQL via pgvector.  On each new
company, queries for similar already-verified entities — useful for
deduplication and for reusing ATS detection from known matches.

Requires: pgvector extension enabled in PostgreSQL, company_embeddings table
(see db/init/011_pgvector_embeddings.sql).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from psycopg.rows import dict_row

from common.db import get_pool

log = logging.getLogger("verifier.graph.vectorstore")


class PgVectorStore:
    """Thin wrapper around pgvector for company entity matching.

    Uses Ollama embeddings via HTTP and stores/queries vectors directly
    in PostgreSQL using psycopg + pgvector.
    """

    def __init__(self, ollama_base_url: str, model: str = "llama3"):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = model

    async def _embed(self, text: str) -> list[float] | None:
        """Generate an embedding vector from Ollama."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                resp = await client.post(
                    f"{self.ollama_base_url}/api/embed",
                    json={"model": self.model, "input": text},
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings")
                if embeddings and len(embeddings) > 0:
                    return embeddings[0]
                return None
        except Exception:
            log.debug("Ollama embedding failed for %r", text[:80], exc_info=True)
            return None

    def _embed_sync(self, text: str) -> list[float] | None:
        """Synchronous embedding for use outside async context."""
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                resp = client.post(
                    f"{self.ollama_base_url}/api/embed",
                    json={"model": self.model, "input": text},
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings")
                if embeddings and len(embeddings) > 0:
                    return embeddings[0]
                return None
        except Exception:
            log.debug("Ollama embedding (sync) failed for %r", text[:80], exc_info=True)
            return None

    async def query_similar(
        self,
        company_name: str,
        k: int = 3,
        score_threshold: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Find similar previously-verified companies via cosine similarity.

        Returns list of dicts: {company_id, name, distance, careers_url, ats_platform}.
        Lower distance = more similar.
        """
        vec = await self._embed(company_name)
        if not vec:
            return []

        pool = get_pool()
        try:
            with pool.connection() as conn:
                conn.row_factory = dict_row
                rows = conn.execute(
                    """
                    SELECT
                        ce.company_id,
                        c.name,
                        ce.embedding <=> %s::vector AS distance,
                        cs.result->>'careers_url' AS careers_url,
                        cs.result->>'ats_platform' AS ats_platform
                    FROM company_embeddings ce
                    JOIN companies c ON c.id = ce.company_id
                    LEFT JOIN company_signals cs
                        ON cs.company_id = ce.company_id AND cs.check_type = 'careers'
                    WHERE ce.embedding <=> %s::vector < %s
                    ORDER BY ce.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vec, vec, score_threshold, vec, k),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            log.debug("pgvector query failed for %r", company_name, exc_info=True)
            return []

    async def store_result(
        self,
        company_name: str,
        *,
        company_id: str,
    ) -> None:
        """Store a company embedding for future entity matching."""
        vec = await self._embed(company_name)
        if not vec:
            return

        pool = get_pool()
        try:
            with pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO company_embeddings (company_id, embedding)
                    VALUES (%s, %s::vector)
                    ON CONFLICT (company_id) DO UPDATE
                        SET embedding = EXCLUDED.embedding,
                            updated_at = now()
                    """,
                    (company_id, vec),
                )
        except Exception:
            log.debug("pgvector store failed for %r", company_name, exc_info=True)


def get_vectorstore(
    ollama_base_url: str,
    model: str = "llama3",
) -> PgVectorStore | None:
    """Create a PgVectorStore instance, or None if Ollama is unavailable."""
    if not ollama_base_url:
        return None
    return PgVectorStore(ollama_base_url, model=model)
