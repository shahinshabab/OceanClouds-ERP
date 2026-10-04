# crm/forms.py
from django import forms
from django.contrib.auth import get_user_model

from common.forms import BootstrapModelForm
from common.geo import (
    COUNTRY_CHOICES,
    DEFAULT_COUNTRY,
    INDIAN_STATE_CHOICES,
    INDIAN_STATES,
    normalize_phone,
    phone_hint,
)

from .models import Client, Contact, Inquiry, Lead, Review


CRM_MANAGER_GROUP_NAMES = ["CRM Manager", "crm_manager", "CRM_MANAGER"]


class ClientForm(BootstrapModelForm):
    class Meta:
        model = Client
        fields = [
            "name", "display_name", "email", "phone", "billing_address",
            "city", "district", "state", "country", "notes", "is_active",
        ]
        widgets = {
            "billing_address": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class ContactForm(BootstrapModelForm):
    class Meta:
        model = Contact
        fields = [
            "client", "first_name", "last_name", "role", "email", "phone",
            "whatsapp", "is_primary", "allow_marketing",
        ]


class InquiryForm(BootstrapModelForm):
    class Meta:
        model = Inquiry
        fields = [
            "channel", "status", "name", "email", "phone", "whatsapp",
            "wedding_date", "wedding_city", "wedding_district", "wedding_state", "wedding_country",
            "message", "lead", "client", "handled_by",
        ]
        widgets = {
            "wedding_date": forms.DateInput(attrs={"type": "date"}),
            "message": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        managers_qs = User.objects.filter(
            groups__name__in=CRM_MANAGER_GROUP_NAMES,
            is_active=True,
        ).distinct().order_by("first_name", "last_name", "username", "id")

        self.fields["handled_by"].queryset = managers_qs
        self.fields["handled_by"].label = "Assigned manager"
        self.fields["handled_by"].empty_label = "Select manager"

        self.fields["lead"].required = False
        self.fields["client"].required = False
        self.fields["handled_by"].required = False

        if not self.instance.pk and managers_qs.exists() and not self.initial.get("handled_by"):
            self.initial["handled_by"] = managers_qs.first().pk


class LeadForm(BootstrapModelForm):
    """
    Country and state are picked from lists (India by default); phone and
    WhatsApp numbers are checked against the country's digit count and saved
    with the country code. The wedding needs only a city and a country.
    """

    country = forms.ChoiceField(choices=COUNTRY_CHOICES, initial=DEFAULT_COUNTRY)
    state = forms.ChoiceField(choices=INDIAN_STATE_CHOICES, required=False)
    wedding_country = forms.ChoiceField(choices=COUNTRY_CHOICES, initial=DEFAULT_COUNTRY)

    class Meta:
        model = Lead
        fields = [
            "inquiry", "client", "name", "email", "phone", "whatsapp",
            "country", "state",
            "wedding_date", "wedding_city", "wedding_country",
            "budget_min", "budget_max", "status", "source", "source_detail",
            "notes", "next_action_date", "next_action_note",
        ]
        widgets = {
            "wedding_date": forms.DateInput(attrs={"type": "date"}),
            "next_action_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "source_detail": forms.TextInput(attrs={"placeholder": "Eg. Referral name, Instagram campaign, expo title"}),
            "next_action_note": forms.TextInput(attrs={"placeholder": "Eg. Call client tomorrow, send package details"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Keep a value from older data that is not in the lists.
        for name in ("country", "wedding_country"):
            current = self.initial.get(name) or getattr(self.instance, name, "")
            if current and current not in dict(COUNTRY_CHOICES):
                self.fields[name].choices = [(current, current)] + COUNTRY_CHOICES
        current_state = self.initial.get("state") or getattr(self.instance, "state", "")
        if current_state and current_state not in INDIAN_STATES:
            self.fields["state"].choices = INDIAN_STATE_CHOICES + [(current_state, current_state)]

        self.fields["country"].label = "Country"
        self.fields["state"].label = "State"
        self.fields["wedding_city"].required = True
        self.fields["wedding_country"].label = "Wedding country"
        country = self.data.get(self.add_prefix("country")) if self.is_bound else (
            self.initial.get("country") or self.instance.country or DEFAULT_COUNTRY
        )
        hint = phone_hint(country)
        for name in ("phone", "whatsapp"):
            self.fields[name].help_text = hint
            self.fields[name].widget.attrs.update({"inputmode": "tel", "autocomplete": "tel"})

    def _clean_phone(self, name):
        value = self.cleaned_data.get(name, "")
        if self.instance.pk and name not in self.changed_data and "country" not in self.changed_data:
            # Older leads keep the number they were saved with until it is edited.
            return value
        country = self.cleaned_data.get("country") or DEFAULT_COUNTRY
        try:
            return normalize_phone(value, country)
        except forms.ValidationError as error:
            self.add_error(name, error)
            return value

    def clean(self):
        cleaned = super().clean()
        cleaned["phone"] = self._clean_phone("phone")
        cleaned["whatsapp"] = self._clean_phone("whatsapp")
        if cleaned.get("country") != "India":
            # The state list is India's; other countries leave it empty.
            cleaned["state"] = ""
        return cleaned


class ReviewForm(BootstrapModelForm):
    class Meta:
        model = Review
        fields = ["client", "rating", "title", "comment", "next_action", "next_action_date"]
        widgets = {
            "rating": forms.Select(choices=[("", "Select rating")] + [(i, str(i)) for i in range(1, 6)]),
            "comment": forms.Textarea(attrs={"rows": 4}),
            "next_action": forms.TextInput(attrs={"placeholder": "Eg. Follow-up call, request testimonial"}),
            "next_action_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_rating(self):
        rating = self.cleaned_data.get("rating")
        if rating is not None and not (1 <= rating <= 5):
            raise forms.ValidationError("Rating must be between 1 and 5.")
        return rating
