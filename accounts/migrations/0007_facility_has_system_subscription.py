from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_remove_modality_node_unique_together'),
    ]

    operations = [
        migrations.AddField(
            model_name='facility',
            name='has_system_subscription',
            field=models.BooleanField(default=False, help_text='Access to the full NoctisPro system'),
        ),
    ]
