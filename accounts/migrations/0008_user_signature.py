from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_facility_has_system_subscription'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='signature',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Base64-encoded digital signature image (data URL). Auto-applied when signing reports.',
            ),
        ),
    ]
