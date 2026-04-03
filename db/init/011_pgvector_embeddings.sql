-- pgvector extension and company embeddings table for entity matching.
-- Used by the LangGraph discovery cascade to find similar previously-verified
-- companies and reuse ATS detection results.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS company_embeddings (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   UUID NOT NULL REFERENCES companies(id),
    embedding    vector(4096),  -- Llama3 embedding dimension
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id)
);

-- No ANN index — pgvector HNSW/IVFFlat cap at 2000 dimensions, and Llama3
-- embeddings are 4096.  Exact cosine search is fast enough at our scale
-- (<100k verified companies).  If we switch to a smaller embedding model
-- (e.g. nomic-embed-text at 768d), add an HNSW index then.
