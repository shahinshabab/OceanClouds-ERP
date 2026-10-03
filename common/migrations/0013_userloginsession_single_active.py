import django.db.models
import django.utils.timezone
from django.db import migrations, models


def close_duplicate_active_sessions(apps, schema_editor):
    UserLoginSession = apps.get_model("common", "UserLoginSession")
    Session = apps.get_model("sessions", "Session")
    database = schema_editor.connection.alias
    now = django.utils.timezone.now()
    seen_user_ids = set()
    replaced_session_keys = []

    active_sessions = (
        UserLoginSession.objects.using(database)
        .filter(logout_at__isnull=True)
        .order_by("user_id", "-login_at", "-pk")
    )
    for login_session in active_sessions.iterator():
        if login_session.user_id not in seen_user_ids:
            seen_user_ids.add(login_session.user_id)
            continue

        login_session.logout_at = now
        login_session.end_reason = "session_replaced"
        login_session.save(
            using=database,
            update_fields=["logout_at", "end_reason"],
        )
        replaced_session_keys.append(login_session.session_key)

    if replaced_session_keys:
        Session.objects.using(database).filter(
            session_key__in=replaced_session_keys
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0012_delete_systemsetting"),
        ("sessions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userloginsession",
            name="last_activity_at",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
            ),
        ),
        migrations.AlterField(
            model_name="userloginsession",
            name="end_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("logout", "Manual Logout"),
                    ("auto_timeout", "Auto Timeout"),
                    ("session_replaced", "Replaced by New Login"),
                    ("system", "System"),
                    ("unknown", "Unknown"),
                ],
                db_index=True,
                default="",
                max_length=30,
            ),
        ),
        migrations.RunPython(
            close_duplicate_active_sessions,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="userloginsession",
            constraint=models.UniqueConstraint(
                condition=django.db.models.Q(logout_at__isnull=True),
                fields=("user",),
                name="one_active_login_session_per_user",
            ),
        ),
    ]
