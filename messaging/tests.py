from django.core.exceptions import ValidationError
from django.test import override_settings

from common.test_helpers import AuthenticatedViewTestMixin, make_user

from .forms import CampaignForm, WhatsAppTemplateForm
from .models import (
    Campaign,
    CampaignRecipient,
    EmailSendLog,
    EmailTemplate,
    Ticket,
    WhatsAppSendLog,
    WhatsAppTemplate,
)


class MessagingTests(AuthenticatedViewTestMixin):
    list_url_names = [
        "messaging:template_list",
        "messaging:whatsapp_template_list",
        "messaging:campaign_list",
        "messaging:whatsapp_log_list",
        "messaging:ticket_list",
    ]

    def test_email_template_requires_pdf_mode_when_attaching_generated_pdf(self):
        template = EmailTemplate(
            name="Proposal",
            slug="proposal",
            type=EmailTemplate.TemplateType.PROPOSAL,
            subject="Subject",
            body_html="<p>Hello</p>",
            attach_generated_pdf=True,
        )

        with self.assertRaises(ValidationError):
            template.full_clean()

    @override_settings(EMAIL_DEFAULT_FROM="from@example.com", EMAIL_DEFAULT_REPLY_TO="reply@example.com")
    def test_campaign_effective_sender_fields_fall_back_to_settings(self):
        template = EmailTemplate.objects.create(
            name="Campaign",
            slug="campaign",
            type=EmailTemplate.TemplateType.CAMPAIGN,
            subject="Subject",
            body_html="<p>Hello</p>",
        )
        campaign = Campaign.objects.create(name="Newsletter", template=template)

        self.assertEqual(campaign.effective_from_email, "from@example.com")
        self.assertEqual(campaign.effective_reply_to, "reply@example.com")

    def test_campaign_form_requires_start_fields_for_scheduled_status(self):
        template = EmailTemplate.objects.create(
            name="Campaign",
            slug="campaign-form",
            type=EmailTemplate.TemplateType.CAMPAIGN,
            subject="Subject",
            body_html="<p>Hello</p>",
        )
        form = CampaignForm(
            data={
                "name": "Scheduled",
                "template": template.pk,
                "target_type": Campaign.TargetType.CLIENT_MARKETING,
                "description": "",
                "from_email": "",
                "reply_to": "",
                "status": Campaign.Status.SCHEDULED,
                "start_date": "",
                "start_time": "",
                "weekdays_only": "on",
                "daily_limit": 50,
                "delay_seconds": 5,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("start_date", form.errors)
        self.assertIn("start_time", form.errors)

    def test_send_logs_mark_sent_and_failed(self):
        email_log = EmailSendLog.objects.create(to_email="client@example.com")
        email_log.mark_sent("ses-1")
        email_log.refresh_from_db()
        self.assertEqual(email_log.status, EmailSendLog.Status.SENT)
        self.assertEqual(email_log.ses_message_id, "ses-1")

        whatsapp_log = WhatsAppSendLog.objects.create(to_number="+910000000000")
        whatsapp_log.mark_failed("No provider", {"ok": False})
        whatsapp_log.refresh_from_db()
        self.assertEqual(whatsapp_log.status, WhatsAppSendLog.Status.FAILED)
        self.assertEqual(whatsapp_log.raw_response, {"ok": False})

    def test_campaign_recipient_mark_sent(self):
        template = EmailTemplate.objects.create(
            name="Campaign Recipient",
            slug="campaign-recipient",
            type=EmailTemplate.TemplateType.CAMPAIGN,
            subject="Subject",
            body_html="<p>Hello</p>",
        )
        campaign = Campaign.objects.create(name="Campaign", template=template)
        recipient = CampaignRecipient.objects.create(
            campaign=campaign,
            email="client@example.com",
        )

        recipient.mark_sent()
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, CampaignRecipient.SendStatus.SENT)
        self.assertIsNotNone(recipient.sent_at)

    def test_whatsapp_template_form_parses_variable_order(self):
        form = WhatsAppTemplateForm(
            data={
                "name": "Event Client",
                "slug": "event-client",
                "type": WhatsAppTemplate.TemplateType.EVENT_CLIENT,
                "provider": WhatsAppTemplate.Provider.META,
                "provider_template_name": "event_client",
                "language_code": WhatsAppTemplate.Language.EN,
                "category": WhatsAppTemplate.Category.UTILITY,
                "header_text": "",
                "body_text": "Hello {{ event.name }}",
                "footer_text": "",
                "is_active": "",
                "notes": "",
                "variable_order_raw": "event.name\nvenue.name\n",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["variable_order_raw"],
            ["event.name", "venue.name"],
        )

    def test_ticket_number_auto_increments(self):
        user = make_user(username="ticket-user")
        first = Ticket.objects.create(
            created_by=user,
            subject="First",
            description="First ticket",
        )
        second = Ticket.objects.create(
            created_by=user,
            subject="Second",
            description="Second ticket",
        )

        self.assertEqual(first.ticket_number, 1)
        self.assertEqual(second.ticket_number, 2)
        self.assertIn("Ticket #2", str(second))
