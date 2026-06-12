from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("smartInterviewApp", "0055_litio_assistant"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
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

            ALTER TABLE "smartInterviewApp_litioassistantmessage"
                ADD COLUMN IF NOT EXISTS "metadata" jsonb NOT NULL DEFAULT '{}'::jsonb;

            ALTER TABLE "smartInterviewApp_litioassistantmessage"
                ADD COLUMN IF NOT EXISTS "created_at" timestamp with time zone NOT NULL DEFAULT NOW();

            ALTER TABLE "smartInterviewApp_litioassistantfeedback"
                ADD COLUMN IF NOT EXISTS "metadata" jsonb NOT NULL DEFAULT '{}'::jsonb;

            ALTER TABLE "smartInterviewApp_litioassistantfeedback"
                ADD COLUMN IF NOT EXISTS "created_at" timestamp with time zone NOT NULL DEFAULT NOW();
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
