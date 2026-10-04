from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from common.test_helpers import AuthenticatedViewTestMixin

from .forms import InquiryForm, ReviewForm
from .models import Client, Contact, Inquiry, Lead, Review


class CrmTests(AuthenticatedViewTestMixin):
    list_url_names = [
        "crm:client_list",
        "crm:contact_list",
        "crm:lead_list",
        "crm:inquiry_list",
        "crm:review_list",
    ]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.client_obj = Client.objects.create(name="Ocean Client")

    def test_client_primary_contact_returns_primary_contact(self):
        secondary = Contact.objects.create(client=self.client_obj, first_name="Alex")
        primary = Contact.objects.create(
            client=self.client_obj,
            first_name="Riya",
            is_primary=True,
        )

        self.assertEqual(self.client_obj.primary_contact, primary)
        self.assertIn("Alex", str(secondary))

    def test_contact_email_is_unique_per_client_when_present(self):
        Contact.objects.create(
            client=self.client_obj,
            first_name="A",
            email="same@example.com",
        )

        with self.assertRaises(IntegrityError):
            Contact.objects.create(
                client=self.client_obj,
                first_name="B",
                email="same@example.com",
            )

    def test_inquiry_requires_at_least_one_contact_field(self):
        inquiry = Inquiry(channel="website")

        with self.assertRaises(ValidationError):
            inquiry.clean()

    def test_inquiry_and_lead_strings(self):
        inquiry = Inquiry.objects.create(name="Priya")
        lead = Lead.objects.create(name="Priya Lead", inquiry=inquiry)

        self.assertIn("Open", str(inquiry))
        self.assertIn("New", str(lead))

    def test_review_rating_property_and_validation(self):
        review = Review.objects.create(client=self.client_obj, title="Great", rating=5)
        form = ReviewForm(
            data={
                "client": self.client_obj.pk,
                "rating": 6,
                "title": "Too high",
                "comment": "",
                "next_action": "",
                "next_action_date": "",
            }
        )

        self.assertTrue(review.has_rating)
        self.assertFalse(form.is_valid())
        self.assertIn("rating", form.errors)

    def test_inquiry_form_is_valid_with_name_only(self):
        form = InquiryForm(
            data={
                "channel": "website",
                "status": Inquiry.STATUS_OPEN,
                "name": "New Inquiry",
                "email": "",
                "phone": "",
                "whatsapp": "",
                "wedding_date": "",
                "wedding_city": "",
                "wedding_district": "",
                "wedding_state": "Kerala",
                "wedding_country": "India",
                "message": "",
                "lead": "",
                "client": "",
                "handled_by": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_detail_urls_reverse(self):
        self.assertEqual(
            reverse("crm:client_detail", args=[self.client_obj.pk]),
            f"/crm/clients/{self.client_obj.pk}/",
        )


class PhoneRuleTests(TestCase):
    def test_indian_numbers_need_ten_digits(self):
        from common.geo import normalize_phone

        self.assertEqual(normalize_phone("98470 12345"), "+91 9847012345")
        self.assertEqual(normalize_phone("+91 98470-12345"), "+91 9847012345")
        self.assertEqual(normalize_phone("09847012345"), "+91 9847012345")
        with self.assertRaises(ValidationError):
            normalize_phone("984701234")

    def test_other_countries_use_their_own_length(self):
        from common.geo import normalize_phone

        self.assertEqual(normalize_phone("50 123 4567", "United Arab Emirates"), "+971 501234567")
        # A number typed with another country's code is checked against it.
        self.assertEqual(normalize_phone("+971 50 123 4567"), "+971 501234567")
        with self.assertRaises(ValidationError):
            normalize_phone("12345678", "United Arab Emirates")

    def test_lead_form_saves_country_and_formatted_phone(self):
        from .forms import LeadForm

        form = LeadForm(data={
            "name": "Anu & Rahul",
            "status": "new",
            "country": "India",
            "state": "Kerala",
            "phone": "9847012345",
            "wedding_city": "Kochi",
            "wedding_country": "India",
        })
        self.assertTrue(form.is_valid(), form.errors)
        lead = form.save()
        self.assertEqual(lead.phone, "+91 9847012345")
        self.assertEqual(lead.state, "Kerala")

        bad = LeadForm(data={"name": "X", "status": "new", "country": "India", "phone": "12345", "wedding_city": "Kochi", "wedding_country": "India"})
        self.assertFalse(bad.is_valid())
        self.assertIn("phone", bad.errors)
