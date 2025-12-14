from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationpreference",
            name="preferred_method",
            field=models.CharField(
                choices=[
                    ("web", "Web Notification"),
                    ("email", "Email"),
                    ("sms", "SMS"),
                    ("call", "Phone Call"),
                    ("push", "Push Notification"),
                ],
                default="web",
                max_length=20,
            ),
        ),
    ]

