# sales/forms.py

from django import forms

from common.forms import BootstrapModelForm
from services.models import Service, Package

from .models import (
    Deal,
    Proposal,
    ProposalPlan,
    ProposalEventDay,
    ProposalItem,
    ProposalItemDeliverable,
    Contract,
    Invoice,
    Payment,
)


class DateInput(forms.DateInput):
    input_type = "date"


class TimeInput(forms.TimeInput):
    input_type = "time"


# ---------------------------------------------------------
# Catalog choices helper
# ---------------------------------------------------------

def get_catalog_choices():
    service_choices = [
        (f"S:{service.id}", f"Service — {service.name}")
        for service in Service.objects.filter(is_active=True).only("id", "name").order_by("name")
    ]

    package_choices = [
        (f"P:{package.id}", f"Package — {package.name}")
        for package in Package.objects.filter(is_active=True).only("id", "name").order_by("name")
    ]

    return [("", "Select item...")] + service_choices + package_choices


# ---------------------------------------------------------
# Deal
# ---------------------------------------------------------

class DealForm(BootstrapModelForm):
    class Meta:
        model = Deal
        fields = [
            "name",
            "client",
            "lead",
            "stage",
            "amount",
            "expected_close_date",
            "description",
            "is_active",
            "closed_on",
        ]

        widgets = {
            "expected_close_date": DateInput(),
            "closed_on": DateInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }


# ---------------------------------------------------------
# Proposal
# ---------------------------------------------------------

class ProposalForm(BootstrapModelForm):
    class Meta:
        model = Proposal
        fields = [
            "deal",
            "title",
            "version",
            "status",
            "valid_until",
            "notes",
        ]

        widgets = {
            "valid_until": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


# ---------------------------------------------------------
# Proposal Plan
# ---------------------------------------------------------

class ProposalPlanForm(BootstrapModelForm):
    class Meta:
        model = ProposalPlan
        fields = [
            "name",
            "description",
            "is_primary",
            "is_accepted",
            "discount",
            "tax_rate",
            "sort_order",
        ]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "discount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "tax_rate": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "Eg. 18",
                }
            ),
            "sort_order": forms.NumberInput(attrs={"min": "0"}),
        }

        labels = {
            "discount": "Discount Amount",
            "tax_rate": "Tax %",
        }

        help_texts = {
            "discount": "Enter fixed discount amount for this plan.",
            "tax_rate": "Enter tax percentage, for example 18 for 18%.",
        }


# ---------------------------------------------------------
# Proposal Event Day
# ---------------------------------------------------------

class ProposalEventDayForm(BootstrapModelForm):
    class Meta:
        model = ProposalEventDay
        fields = [
            "event_date",
            "title",
            "venue",
            "start_time",
            "end_time",
            "notes",
            "sort_order",
        ]

        widgets = {
            "event_date": DateInput(),
            "start_time": TimeInput(),
            "end_time": TimeInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "sort_order": forms.NumberInput(attrs={"min": "0"}),
        }


# ---------------------------------------------------------
# Proposal Item
# ---------------------------------------------------------

class ProposalItemForm(BootstrapModelForm):
    catalog_item = forms.ChoiceField(
        choices=[],
        required=False,
        label="Item",
        widget=forms.Select(attrs={"class": "catalog-item"}),
    )

    class Meta:
        model = ProposalItem
        fields = [
            "catalog_item",
            "description",
            "quantity",
            "unit_price",
            "notes",
            "sort_order",
        ]

        widgets = {
            "description": forms.TextInput(
                attrs={"placeholder": "Example: Wedding Photography"}
            ),
            "quantity": forms.NumberInput(attrs={"min": "1"}),
            "unit_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "sort_order": forms.NumberInput(attrs={"min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        catalog_choices = kwargs.pop("catalog_choices", None)
        super().__init__(*args, **kwargs)

        self.fields["catalog_item"].choices = catalog_choices or get_catalog_choices()

        if self.instance and self.instance.pk:
            if self.instance.service_id:
                self.initial["catalog_item"] = f"S:{self.instance.service_id}"
            elif self.instance.package_id:
                self.initial["catalog_item"] = f"P:{self.instance.package_id}"

    def clean(self):
        cleaned_data = super().clean()
        catalog_item = (cleaned_data.get("catalog_item") or "").strip()

        if not catalog_item:
            raise forms.ValidationError("Please select a Service or Package.")

        try:
            item_type, item_id = catalog_item.split(":")
            item_id = int(item_id)
        except ValueError:
            raise forms.ValidationError("Invalid item selected.")

        self.instance.service = None
        self.instance.package = None

        if item_type == "S":
            service = Service.objects.filter(id=item_id, is_active=True).first()

            if not service:
                raise forms.ValidationError("Selected service does not exist or is inactive.")

            self.instance.service = service

            if service.name.strip().lower() == "other":
                description = (cleaned_data.get("description") or "").strip()
                unit_price = cleaned_data.get("unit_price")

                if not description:
                    self.add_error(
                        "description",
                        "Please enter a description for 'Other'.",
                    )

                if unit_price is None or unit_price <= 0:
                    self.add_error(
                        "unit_price",
                        "Please enter a price for 'Other' item.",
                    )

        elif item_type == "P":
            package = Package.objects.filter(id=item_id, is_active=True).first()

            if not package:
                raise forms.ValidationError("Selected package does not exist or is inactive.")

            self.instance.package = package

        else:
            raise forms.ValidationError("Invalid item type selected.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        catalog_item = self.cleaned_data.get("catalog_item") or ""
        item_type, item_id = catalog_item.split(":")
        item_id = int(item_id)

        instance.service = None
        instance.package = None

        if item_type == "S":
            instance.service_id = item_id
        elif item_type == "P":
            instance.package_id = item_id

        if commit:
            instance.save()

        return instance


# ---------------------------------------------------------
# Proposal Item Deliverable
# ---------------------------------------------------------

class ProposalItemDeliverableForm(BootstrapModelForm):
    class Meta:
        model = ProposalItemDeliverable
        fields = [
            "title",
            "description",
            "quantity",
            "unit",
            "sort_order",
            "is_included",
        ]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "sort_order": forms.NumberInput(attrs={"min": "0"}),
        }


# ---------------------------------------------------------
# Contract
# ---------------------------------------------------------

class ContractForm(BootstrapModelForm):
    class Meta:
        model = Contract
        fields = [
            "deal",
            "proposal",
            "proposal_plan",
            "status",
            "signed_date",
            "start_date",
            "end_date",
            "terms",
            "file",
        ]

        widgets = {
            "signed_date": DateInput(),
            "start_date": DateInput(),
            "end_date": DateInput(),
            "terms": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        proposal_id = None

        if self.is_bound:
            proposal_id = self.data.get(self.add_prefix("proposal"))
        elif self.instance and self.instance.proposal_id:
            proposal_id = self.instance.proposal_id
        elif self.initial.get("proposal"):
            proposal_id = self.initial.get("proposal")

        if proposal_id:
            self.fields["proposal_plan"].queryset = ProposalPlan.objects.filter(
                proposal_id=proposal_id
            ).order_by("sort_order", "id")
        else:
            self.fields["proposal_plan"].queryset = ProposalPlan.objects.none()



# ---------------------------------------------------------
# Invoice
# ---------------------------------------------------------

class InvoiceForm(BootstrapModelForm):
    class Meta:
        model = Invoice
        fields = [
            "deal",
            "contract",
            "issue_date",
            "due_date",
            "status",
            "discount",
            "tax_rate",
            "notes",
        ]

        widgets = {
            "issue_date": DateInput(),
            "due_date": DateInput(),
            "discount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "tax_rate": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

        labels = {
            "discount": "Discount Amount",
            "tax_rate": "Tax %",
        }

# ---------------------------------------------------------
# Payment
# ---------------------------------------------------------

class PaymentForm(BootstrapModelForm):
    class Meta:
        model = Payment
        fields = [
            "invoice",
            "date",
            "amount",
            "payment_type",
            "method",
            "reference",
            "notes",
            "received_by",
        ]

        widgets = {
            "date": DateInput(),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        invoice_obj = None

        initial_invoice_id = self.initial.get("invoice")
        data_invoice_id = self.data.get(self.add_prefix("invoice")) if self.is_bound else None

        invoice_id = data_invoice_id or initial_invoice_id

        if invoice_id:
            try:
                invoice_obj = Invoice.objects.get(pk=invoice_id)
            except Invoice.DoesNotExist:
                invoice_obj = None

        if invoice_obj:
            remaining = invoice_obj.balance
            self.fields["amount"].widget.attrs["max"] = remaining
            self.fields["amount"].help_text = f"Remaining balance: {remaining}"
