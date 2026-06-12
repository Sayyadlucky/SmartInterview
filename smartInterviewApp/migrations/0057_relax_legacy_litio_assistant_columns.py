from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("smartInterviewApp", "0056_repair_litio_assistant_schema"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            DECLARE
                col_name text;
            BEGIN
                -- The local/prod DB may contain legacy columns from an earlier
                -- Litio Assistant draft. They are no longer used by the current
                -- Django model, so they must not block inserts.
                FOR col_name IN
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'smartInterviewApp_litioassistantconversation'
                      AND is_nullable = 'NO'
                      AND column_default IS NULL
                      AND column_name NOT IN (
                          'id',
                          'user_id',
                          'title',
                          'status',
                          'metadata',
                          'created_at',
                          'updated_at'
                      )
                LOOP
                    EXECUTE format(
                        'ALTER TABLE "smartInterviewApp_litioassistantconversation" ALTER COLUMN %I DROP NOT NULL',
                        col_name
                    );
                END LOOP;

                FOR col_name IN
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'smartInterviewApp_litioassistantmessage'
                      AND is_nullable = 'NO'
                      AND column_default IS NULL
                      AND column_name NOT IN (
                          'id',
                          'conversation_id',
                          'sender',
                          'content',
                          'metadata',
                          'created_at'
                      )
                LOOP
                    EXECUTE format(
                        'ALTER TABLE "smartInterviewApp_litioassistantmessage" ALTER COLUMN %I DROP NOT NULL',
                        col_name
                    );
                END LOOP;

                FOR col_name IN
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'smartInterviewApp_litioassistantfeedback'
                      AND is_nullable = 'NO'
                      AND column_default IS NULL
                      AND column_name NOT IN (
                          'id',
                          'message_id',
                          'rating',
                          'comment',
                          'metadata',
                          'created_at'
                      )
                LOOP
                    EXECUTE format(
                        'ALTER TABLE "smartInterviewApp_litioassistantfeedback" ALTER COLUMN %I DROP NOT NULL',
                        col_name
                    );
                END LOOP;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
