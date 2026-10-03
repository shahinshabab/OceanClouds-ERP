from decimal import Decimal

from django.db import migrations, models
from django.db.models import Sum


def copy_contract_pricing_to_invoices(apps, schema_editor):
    Invoice = apps.get_model("sales", "Invoice")

    for invoice in Invoice.objects.select_related("contract").all():
        contract = invoice.contract

        if not contract:
            continue

        invoice.discount = contract.discount or Decimal("0.00")
        invoice.tax_rate = contract.tax_rate or Decimal("0.00")

        subtotal = (
            invoice.items.aggregate(subtotal=Sum("line_subtotal"))["subtotal"]
            or Decimal("0.00")
        )
        taxable_amount = subtotal - (invoice.discount or Decimal("0.00"))
        if taxable_amount < Decimal("0.00"):
            taxable_amount = Decimal("0.00")

        invoice.subtotal = subtotal
        invoice.tax = (taxable_amount * (invoice.tax_rate or Decimal("0.00"))) / Decimal("100.00")
        invoice.total = taxable_amount + invoice.tax
        invoice.save(
            update_fields=[
                "subtotal",
                "discount",
                "tax_rate",
                "tax",
                "total",
            ]
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0013_proposaleventday_alter_contractitem_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="discount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="tax_rate",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=5,
            ),
        ),
        migrations.RunPython(copy_contract_pricing_to_invoices, noop_reverse),
    ]
