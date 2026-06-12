from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("smartInterviewApp", "0057_relax_legacy_litio_assistant_columns"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- Knowledge table
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


            -- Conversation table
            ALTER TABLE "smartInterviewApp_litioassistantconversation"
                ADD COLUMN IF NOT EXISTS "title" varchar(180) NOT NULL DEFAULT 'Litio Assistant Chat';

            ALTER TABLE "smartInterviewApp_litioassistantconversation"
                ADD COLUMN IF NOT EXISTS "status" varchar(20) NOT NULL DEFAULT 'open';

            ALTER TABLE "smartInterviewApp_litioassistantconversation"
                ADD COLUMN IF NOT EXISTS "metadata" jsonb NOT NULL DEFAULT '{}'::jsonb;

            ALTER TABLE "smartInterviewApp_litioassistantconversation"
                ADD COLUMN IF NOT EXISTS "created_at" timestamp with time zone NOT NULL DEFAULT NOW();

            ALTER TABLE "smartInterviewApp_litioassistantconversation"
                ADD COLUMN IF NOT EXISTS "updated_at" timestamp with time zone NOT NULL DEFAULT NOW();


            -- Message table
            ALTER TABLE "smartInterviewApp_litioassistantmessage"
                ADD COLUMN IF NOT EXISTS "sender" varchar(20) NOT NULL DEFAULT 'assistant';

            ALTER TABLE "smartInterviewApp_litioassistantmessage"
                ADD COLUMN IF NOT EXISTS "content" text NOT NULL DEFAULT '';

            ALTER TABLE "smartInterviewApp_litioassistantmessage"
                ADD COLUMN IF NOT EXISTS "intent_key" varchar(120) NOT NULL DEFAULT '';

            ALTER TABLE "smartInterviewApp_litioassistantmessage"
                ADD COLUMN IF NOT EXISTS "confidence" numeric(5,2) NOT NULL DEFAULT 0;

            ALTER TABLE "smartInterviewApp_litioassistantmessage"
                ADD COLUMN IF NOT EXISTS "metadata" jsonb NOT NULL DEFAULT '{}'::jsonb;

            ALTER TABLE "smartInterviewApp_litioassistantmessage"
                ADD COLUMN IF NOT EXISTS "created_at" timestamp with time zone NOT NULL DEFAULT NOW();


            -- Feedback table
            ALTER TABLE "smartInterviewApp_litioassistantfeedback"
                ADD COLUMN IF NOT EXISTS "rating" varchar(20) NOT NULL DEFAULT 'helpful';

            ALTER TABLE "smartInterviewApp_litioassistantfeedback"
                ADD COLUMN IF NOT EXISTS "comment" text NOT NULL DEFAULT '';

            ALTER TABLE "smartInterviewApp_litioassistantfeedback"
                ADD COLUMN IF NOT EXISTS "metadata" jsonb NOT NULL DEFAULT '{}'::jsonb;

            ALTER TABLE "smartInterviewApp_litioassistantfeedback"
                ADD COLUMN IF NOT EXISTS "created_at" timestamp with time zone NOT NULL DEFAULT NOW();


            -- Relax unused legacy NOT NULL columns only.
            DO $$
            DECLARE
                legacy_col_name text;
                legacy_table_name text;
                allowed_cols text[];
            BEGIN
                FOREACH legacy_table_name IN ARRAY ARRAY[
                    'smartInterviewApp_litioassistantknowledge',
                    'smartInterviewApp_litioassistantconversation',
                    'smartInterviewApp_litioassistantmessage',
                    'smartInterviewApp_litioassistantfeedback'
                ]
                LOOP
                    IF legacy_table_name = 'smartInterviewApp_litioassistantknowledge' THEN
                        allowed_cols := ARRAY[
                            'id','title','intent_key','category','question_patterns','keywords',
                            'answer','priority','is_active','created_at','updated_at'
                        ];
                    ELSIF legacy_table_name = 'smartInterviewApp_litioassistantconversation' THEN
                        allowed_cols := ARRAY[
                            'id','user_id','title','status','metadata','created_at','updated_at'
                        ];
                    ELSIF legacy_table_name = 'smartInterviewApp_litioassistantmessage' THEN
                        allowed_cols := ARRAY[
                            'id','conversation_id','sender','content','intent_key','confidence','metadata','created_at'
                        ];
                    ELSE
                        allowed_cols := ARRAY[
                            'id','message_id','rating','comment','metadata','created_at'
                        ];
                    END IF;

                    FOR legacy_col_name IN
                        SELECT c.column_name
                        FROM information_schema.columns c
                        WHERE c.table_schema = 'public'
                          AND c.table_name = legacy_table_name
                          AND c.is_nullable = 'NO'
                          AND c.column_default IS NULL
                          AND c.is_identity = 'NO'
                          AND NOT (c.column_name = ANY(allowed_cols))
                    LOOP
                        EXECUTE format(
                            'ALTER TABLE %I ALTER COLUMN %I DROP NOT NULL',
                            legacy_table_name,
                            legacy_col_name
                        );
                    END LOOP;
                END LOOP;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
