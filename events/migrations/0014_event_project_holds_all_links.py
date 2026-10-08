from django.db import migrations, models
import django.db.models.deletion


def copy_project_event_links(apps, schema_editor):
    """
    Projects used to point at one event (Project.event). Event.project is now
    the only link, so carry every old link over to the event side. An event
    that already names a project keeps it; otherwise it goes to the newest
    project that pointed at it.
    """
    Event = apps.get_model("events", "Event")
    Project = apps.get_model("projects", "Project")

    projects = (
        Project.objects.filter(event__isnull=False)
        .order_by("event_id", "-created_at")
        .values_list("pk", "event_id")
    )
    seen = set()
    for project_id, event_id in projects:
        if event_id in seen:
            continue
        seen.add(event_id)
        Event.objects.filter(pk=event_id, project__isnull=True).update(project_id=project_id)


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0013_event_contract"),
        ("projects", "0018_alter_deliverable_options_alter_task_options_and_more"),
    ]

    operations = [
        migrations.RunPython(copy_project_event_links, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="event",
            name="project",
            field=models.ForeignKey(
                blank=True,
                help_text="Project this event belongs to. One project can hold several events.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="events",
                to="projects.project",
            ),
        ),
    ]
