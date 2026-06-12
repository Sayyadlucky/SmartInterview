from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("smartInterviewApp", "0058_complete_litio_assistant_schema_repair"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "title" varchar(180) NOT NULL DEFAULT '';

            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "intent_key" varchar(120) NOT NULL DEFAULT '';

            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "category" varchar(80) NOT NULL DEFAULT 'general';

            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "question_patterns" jsonb NOT NULL DEFAULT '[]'::jsonb;

            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "keywords" jsonb NOT NULL DEFAULT '[]'::jsonb;

            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "answer" text NOT NULL DEFAULT '';

            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "priority" integer NOT NULL DEFAULT 100;

            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "is_active" boolean NOT NULL DEFAULT true;

            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "created_at" timestamp with time zone NOT NULL DEFAULT NOW();

            ALTER TABLE "smartInterviewApp_litioassistantknowledge"
                ADD COLUMN IF NOT EXISTS "updated_at" timestamp with time zone NOT NULL DEFAULT NOW();

            DO $$
            DECLARE
                legacy_col_name text;
            BEGIN
                FOR legacy_col_name IN
                    SELECT c.column_name
                    FROM information_schema.columns c
                    WHERE c.table_schema = 'public'
                      AND c.table_name = 'smartInterviewApp_litioassistantknowledge'
                      AND c.is_nullable = 'NO'
                      AND c.column_default IS NULL
                      AND c.is_identity = 'NO'
                      AND c.column_name NOT IN (
                          'id',
                          'title',
                          'intent_key',
                          'category',
                          'question_patterns',
                          'keywords',
                          'answer',
                          'priority',
                          'is_active',
                          'created_at',
                          'updated_at'
                      )
                LOOP
                    EXECUTE format(
                        'ALTER TABLE "smartInterviewApp_litioassistantknowledge" ALTER COLUMN %I DROP NOT NULL',
                        legacy_col_name
                    );
                END LOOP;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
