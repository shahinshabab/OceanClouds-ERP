from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0018_alter_deliverable_options_alter_task_options_and_more"),
        ("events", "0014_event_project_holds_all_links"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="project",
            name="event",
        ),
    ]
