from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('worklist', '0004_study_contrast_agent_study_contrast_used_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='study',
            index=models.Index(fields=['status'], name='worklist_study_status_idx'),
        ),
        migrations.AddIndex(
            model_name='study',
            index=models.Index(fields=['facility'], name='worklist_study_facility_idx'),
        ),
        migrations.AddIndex(
            model_name='study',
            index=models.Index(fields=['study_date'], name='worklist_study_date_idx'),
        ),
        migrations.AddIndex(
            model_name='study',
            index=models.Index(fields=['priority'], name='worklist_study_priority_idx'),
        ),
        migrations.AddIndex(
            model_name='study',
            index=models.Index(fields=['radiologist'], name='worklist_study_radiologist_idx'),
        ),
        migrations.AddIndex(
            model_name='dicomimage',
            index=models.Index(fields=['series'], name='worklist_dicomimage_series_idx'),
        ),
        migrations.AddIndex(
            model_name='series',
            index=models.Index(fields=['study'], name='worklist_series_study_idx'),
        ),
    ]
