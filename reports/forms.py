from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from common.forms import BootstrapModelForm
from common.models import LeaveRequest


class CheckoutCorrectionForm(forms.Form):
    requested_logout_at = forms.DateTimeField(
        label="Actual checkout time",
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    checkout_request_note = forms.CharField(
        label="Reason for missing checkout",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        max_length=1000,
    )

    def __init__(self, *args, login_session=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.login_session = login_session

    def clean_requested_logout_at(self):
        requested = self.cleaned_data["requested_logout_at"]
        if timezone.is_naive(requested):
            requested = timezone.make_aware(requested, timezone.get_current_timezone())
        if not self.login_session:
            return requested
        if requested < self.login_session.login_at:
            raise ValidationError("Checkout cannot be earlier than login.")
        if self.login_session.logout_at and requested > self.login_session.logout_at:
            raise ValidationError("Checkout cannot be later than the session deadline.")
        return requested


class LeaveRequestForm(BootstrapModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["leave_type", "start_date", "end_date", "reason"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date cannot be before start date.")
        return cleaned


class AttendanceReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=(("approve", "Approve"), ("reject", "Reject")),
        widget=forms.HiddenInput(),
    )
    review_note = forms.CharField(
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )


class LeaveReviewForm(AttendanceReviewForm):
    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "reject" and not cleaned.get("review_note"):
            self.add_error("review_note", "Please provide a reason for rejection.")
        return cleaned
