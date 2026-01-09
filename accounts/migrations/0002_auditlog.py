from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("action", models.CharField(choices=[("dicomweb_stow", "DICOMweb STOW-RS upload"), ("dicomweb_qido", "DICOMweb QIDO-RS query"), ("dicomweb_wado", "DICOMweb WADO-RS retrieve"), ("viewer_export", "Viewer export"), ("viewer_print", "Viewer print")], max_length=40)),
                ("study_instance_uid", models.CharField(blank=True, default="", max_length=128)),
                ("series_instance_uid", models.CharField(blank=True, default="", max_length=128)),
                ("sop_instance_uid", models.CharField(blank=True, default="", max_length=128)),
                ("image_id", models.BigIntegerField(blank=True, null=True)),
                ("series_id", models.BigIntegerField(blank=True, null=True)),
                ("study_id", models.BigIntegerField(blank=True, null=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.TextField(blank=True, default="")),
                ("extra", models.JSONField(blank=True, default=dict)),
                ("facility", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_logs", to="accounts.facility")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["created_at"], name="acc_aud_ct"),
                    models.Index(fields=["action", "created_at"], name="acc_aud_act_ct"),
                    models.Index(fields=["study_instance_uid"], name="acc_aud_st_uid"),
                    models.Index(fields=["series_instance_uid"], name="acc_aud_se_uid"),
                    models.Index(fields=["sop_instance_uid"], name="acc_aud_si_uid"),
                ],
            },
        ),
    ]

