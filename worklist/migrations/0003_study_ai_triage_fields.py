from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("worklist", "0002_expand_dicomimage_filefield_lengths"),
    ]

    operations = [
        migrations.AddField(
            model_name="study",
            name="ai_triage_level",
            field=models.CharField(blank=True, db_index=True, default="", max_length=10),
        ),
        migrations.AddField(
            model_name="study",
            name="ai_triage_score",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="study",
            name="ai_triage_flagged",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="study",
            name="ai_last_analyzed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

