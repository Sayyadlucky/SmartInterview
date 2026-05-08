# AI Talent Pool Deployment

## Architecture Summary

The AI Talent Pool now uses a three-stage backend architecture:

1. Candidate indexing
   - parsed resume data is converted into a persistent `CandidateSearchProfile`
   - compact search text, normalized exact skills, family metadata, and embeddings are stored in the database

2. Vector retrieval
   - role/query embedding is computed once
   - PostgreSQL + pgvector retrieves the nearest candidate search profiles
   - only the top shortlist is hydrated for the request

3. Deterministic reranking
   - the existing graph-aware reranker still computes `ai_score`, `ai_band`, explanations, graph evidence, and calibration debug fields

This removes the full candidate scan from request time and is designed for 10k+ candidates comfortably.

## Pinned Dependencies

The backend requires these Python packages:

- `sentence-transformers==3.0.1`
- `torch==2.3.1`
- `scikit-learn==1.5.1`
- `numpy==1.26.4`
- `pgvector==0.3.6`
- `psycopg[binary]==3.2.1`

Install with:

```bash
pip install -r requirements.txt
```

## PostgreSQL + pgvector Setup

Production retrieval is designed for PostgreSQL with pgvector.

1. Install PostgreSQL.
2. Install the pgvector extension package for your environment.
   - Debian/Ubuntu example:

```bash
sudo apt-get install postgresql-16-pgvector
```

3. Create the database and user.
4. Ensure the database is reachable from Django.
5. The Django migration will run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

on PostgreSQL automatically.

## Django Database Configuration

Production should use environment variables like:

```env
DB_ENGINE=postgres
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=smartinterview
POSTGRES_USER=smartinterview
POSTGRES_PASSWORD=change-me
POSTGRES_CONN_MAX_AGE=300
```

If these are not set, the project still defaults to local SQLite for development.

## AI Retrieval Settings

Recommended production settings:

```env
DEBUG=False
AI_TALENT_POOL_REQUIRE_REAL_EMBEDDINGS=True
AI_TALENT_POOL_ENABLE_HASHED_EMBEDDING_FALLBACK=False
AI_TALENT_POOL_REQUIRE_PGVECTOR=True
AI_TALENT_POOL_ENABLE_LOCAL_INDEX_SCAN_FALLBACK=False
AI_TALENT_POOL_RETRIEVAL_SHORTLIST_SIZE=200
AI_TALENT_POOL_DEBUG_LOGGING=False
AI_TALENT_POOL_SENTENCE_TRANSFORMERS_CACHE_DIR=/opt/smartinterview/.cache/sentence-transformers
```

Development-only fallback:

```env
AI_TALENT_POOL_ENABLE_LOCAL_INDEX_SCAN_FALLBACK=True
```

This fallback scans persisted search profiles locally and should not be used as the production path.

## Migrations

Run:

```bash
python manage.py migrate
```

The search index migration creates:

- `CandidateSearchProfile`
- `RoleSearchCache`

and enables the `vector` extension on PostgreSQL.

## Search Index Backfill

After deploying the new schema, backfill the search index:

```bash
python manage.py rebuild_candidate_search_index
```

Optional targeted rebuild:

```bash
python manage.py rebuild_candidate_search_index --candidate-id 101
python manage.py rebuild_candidate_search_index --candidate-id 101 --candidate-id 202
python manage.py rebuild_candidate_search_index --stale-only
```

## Refresh Strategy

The system refreshes `CandidateSearchProfile` automatically when these change:

- `CandidateResume`
- `CandidateResumeSection`
- `Interview`

This keeps indexed search metadata in sync with resume parsing and hiring workflow updates.

## APIs

Existing endpoint preserved:

```text
POST /api/ai-talent-pool/match
```

Example:

```json
{
  "role_id": 12,
  "top_k": 20
}
```

New future-ready endpoint:

```text
POST /api/ai-talent-pool/search
```

Example:

```json
{
  "query": "python fullstack developer with django and angular",
  "filters": {
    "location": "Pune",
    "min_experience": 2,
    "max_experience": 6
  },
  "top_k": 20
}
```

## Audit and Diagnostics

Audit endpoint remains:

```text
GET /api/ai-talent-pool/audit/<role_id>?top_k=20&format=json
GET /api/ai-talent-pool/audit/<role_id>?top_k=20&format=csv
```

The audit payload now includes retrieval diagnostics such as:

- `retrieval_source`
- `prefilter_candidate_count`
- `retrieved_candidate_count`
- `reranked_candidate_count`
- `returned_candidate_count`
- `vector_search_latency_ms`
- `total_request_latency_ms`
- `cached_role_embedding_used`

Per-result retrieval fields include:

- `vector_rank`
- `retrieval_distance`
- `retrieval_similarity`
- `retrieval_source`

## Recommended Rollout Sequence

1. Deploy code and dependencies.
2. Move production to PostgreSQL if not already there.
3. Enable pgvector on the PostgreSQL cluster.
4. Run Django migrations.
5. Backfill the candidate search index:

```bash
python manage.py rebuild_candidate_search_index
```

6. Warm the sentence-transformers model:

```bash
python - <<'PY'
from sentence_transformers import SentenceTransformer
SentenceTransformer("all-MiniLM-L6-v2")
print("model cached")
PY
```

7. Verify indexed retrieval using:
   - `POST /api/ai-talent-pool/match`
   - `POST /api/ai-talent-pool/search`
   - `GET /api/ai-talent-pool/audit/<role_id>?format=json`
8. Review audit output with product/recruiting using CSV export.
9. Enable recruiter traffic.
10. Monitor retrieval latency and result quality.

## Failure Behavior

- Production does not silently fall back to poor retrieval when pgvector is unavailable.
- If indexed pgvector retrieval is required and unavailable, requests fail explicitly with a clear error.
- Local fallback is only allowed when `AI_TALENT_POOL_ENABLE_LOCAL_INDEX_SCAN_FALLBACK=True`.
- Production does not silently downgrade from real sentence-transformer embeddings to hashed embeddings.

## Operational Notes

- The reranker remains deterministic and explainable.
- Graph evidence stays separate from exact skill ownership.
- Retrieval is now vector-first and metadata-aware, while reranking still provides detailed explanations and calibration debug fields.
- This architecture is ready to evolve into richer recruiter search, saved searches, query history, and multi-stage retrieval without changing the UI contract.
