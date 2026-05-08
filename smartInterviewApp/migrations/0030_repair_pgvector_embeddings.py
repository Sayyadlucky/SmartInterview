from django.db import migrations


REPAIR_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

DROP INDEX IF EXISTS cand_search_embedding_hnsw;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'smartInterviewApp_candidatesearchprofile'
          AND column_name = 'embedding'
          AND udt_name <> 'vector'
    ) THEN
        ALTER TABLE "smartInterviewApp_candidatesearchprofile"
        ALTER COLUMN "embedding" TYPE vector(384)
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                WHEN jsonb_typeof(embedding) <> 'array' THEN NULL
                WHEN jsonb_array_length(embedding) = 0 THEN NULL
                ELSE (embedding::text)::vector(384)
            END
        );
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'smartInterviewApp_rolesearchcache'
          AND column_name = 'embedding'
          AND udt_name <> 'vector'
    ) THEN
        ALTER TABLE "smartInterviewApp_rolesearchcache"
        ALTER COLUMN "embedding" TYPE vector(384)
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                WHEN jsonb_typeof(embedding) <> 'array' THEN NULL
                WHEN jsonb_array_length(embedding) = 0 THEN NULL
                ELSE (embedding::text)::vector(384)
            END
        );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS cand_search_embedding_hnsw
ON "smartInterviewApp_candidatesearchprofile"
USING hnsw ("embedding" vector_cosine_ops);
"""


REVERSE_SQL = """
DROP INDEX IF EXISTS cand_search_embedding_hnsw;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0029_candidate_search_profile_status_fields'),
    ]

    operations = [
        migrations.RunSQL(REPAIR_SQL, REVERSE_SQL),
    ]
