from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_user_theme_color_alter_facility_has_ai_subscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="facilitymodalitynode",
            name="enabled",
            field=models.BooleanField(
                default=False,
                help_text="Allow this registered modality to send DICOM studies.",
            ),
        ),
    ]
