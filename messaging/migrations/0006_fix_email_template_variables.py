from django.db import migrations

# The first default templates used field names the models don't have, so
# these values always rendered as "-". Fix them in templates already saved.
REPLACEMENTS = [
    ("proposal.total_amount", "proposal.total"),
    ("invoice.invoice_number", "invoice.number"),
    ("invoice.total_amount", "invoice.total"),
    ("payment.payment_date", "payment.date"),
]


def fix_variables(apps, schema_editor):
    EmailTemplate = apps.get_model("messaging", "EmailTemplate")
    for template in EmailTemplate.objects.all():
        changed = []
        for field in ("subject", "body_html", "body_text"):
            value = getattr(template, field) or ""
            new_value = value
            for old, new in REPLACEMENTS:
                new_value = new_value.replace(old, new)
            if new_value != value:
                setattr(template, field, new_value)
                changed.append(field)
        if changed:
            template.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0005_ticket"),
    ]

    operations = [
        migrations.RunPython(fix_variables, migrations.RunPython.noop),
    ]
