# services/forms.py

from django import forms
from django.forms import inlineformset_factory

from common.forms import BootstrapModelForm

from .models import (
    Vendor,
    Service,
    ServiceDeliverable,
    Package,
    PackageItem,
    PackageDeliverable,
    InventoryItem,
)


class VendorForm(BootstrapModelForm):
    class Meta:
        model = Vendor
        fields = [
            "name",
            "company_name",
            "vendor_type",
            "email",
            "phone",
            "alt_phone",
            "whatsapp",
            "address_line1",
            "address_line2",
            "city",
            "district",
            "state",
            "country",
            "is_preferred",
            "is_active",
            "notes",
        ]

        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "address_line1": forms.TextInput(attrs={"placeholder": "Street / Building"}),
            "address_line2": forms.TextInput(attrs={"placeholder": "Area / Landmark"}),
        }


class ServiceForm(BootstrapModelForm):
    class Meta:
        model = Service
        fields = [
            "name",
            "code",
            "category",
            "summary",
            "description",
            "base_price",
            "price_unit",
            "sort_order",
            "vendors",
            "is_active",
            "notes",
        ]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "base_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }


class ServiceDeliverableForm(BootstrapModelForm):
    class Meta:
        model = ServiceDeliverable
        fields = [
            "title",
            "description",
            "quantity",
            "unit",
            "sort_order",
            "is_active",
        ]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "sort_order": forms.NumberInput(attrs={"min": "0"}),
        }


ServiceDeliverableFormSet = inlineformset_factory(
    Service,
    ServiceDeliverable,
    form=ServiceDeliverableForm,
    extra=1,
    can_delete=True,
)


class PackageForm(BootstrapModelForm):
    class Meta:
        model = Package
        fields = [
            "name",
            "code",
            "tagline",
            "description",
            "price",
            "sort_order",
            "is_active",
            "notes",
        ]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "price": forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "Sum of services"}),
        }


class PackageItemForm(BootstrapModelForm):
    class Meta:
        model = PackageItem
        fields = [
            "service",
            "description",
            "quantity",
            "unit_price",
            "sort_order",
        ]

        widgets = {
            "description": forms.TextInput(
                attrs={"placeholder": "Example: Wedding Photography - Full Day"}
            ),
            "quantity": forms.NumberInput(attrs={"min": 1}),
            "unit_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "sort_order": forms.NumberInput(attrs={"min": "0"}),
        }


PackageItemFormSet = inlineformset_factory(
    Package,
    PackageItem,
    form=PackageItemForm,
    extra=1,
    can_delete=True,
)


class PackageDeliverableForm(BootstrapModelForm):
    class Meta:
        model = PackageDeliverable
        fields = [
            "title",
            "description",
            "quantity",
            "unit",
            "sort_order",
            "is_active",
        ]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "sort_order": forms.NumberInput(attrs={"min": "0"}),
        }


PackageDeliverableFormSet = inlineformset_factory(
    Package,
    PackageDeliverable,
    form=PackageDeliverableForm,
    extra=1,
    can_delete=True,
)


class InventoryItemForm(BootstrapModelForm):
    class Meta:
        model = InventoryItem
        fields = [
            "name",
            "sku",
            "category",
            "service",
            "quantity_total",
            "quantity_available",
            "unit",
            "location",
            "is_active",
            "notes",
        ]

        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "quantity_total": forms.NumberInput(attrs={"min": 0}),
            "quantity_available": forms.NumberInput(attrs={"min": 0}),
        }

    def clean(self):
        cleaned_data = super().clean()

        quantity_total = cleaned_data.get("quantity_total") or 0
        quantity_available = cleaned_data.get("quantity_available") or 0

        if quantity_available > quantity_total:
            self.add_error(
                "quantity_available",
                "Available quantity cannot be greater than total quantity.",
            )

        return cleaned_data