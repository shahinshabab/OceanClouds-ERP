# messaging/signals.py

import logging

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


DEFAULT_EMAIL_TEMPLATES = {
    "proposal": {
        "name": "Default Proposal Email",
        "slug": "proposal-default",
        "subject": "Wedding Service Proposal from {{ company_name }} - {{ proposal.title|default:'Proposal' }}",
        "body_html": """
<div style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#111111;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:24px 0;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;background:#ffffff;border:1px solid #dddddd;">

          <tr>
            <td style="background:#000000;color:#ffffff;padding:28px 32px;text-align:center;">
              <h1 style="margin:0;font-size:26px;letter-spacing:1px;font-weight:700;">
                {{ company_name }}
              </h1>
              <p style="margin:8px 0 0;font-size:13px;letter-spacing:2px;text-transform:uppercase;">
                Wedding & Event Services
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Dear {{ client.name|default:"Client" }},
              </p>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Thank you for considering <strong>{{ company_name }}</strong> for your special occasion.
                We are pleased to share the proposal prepared for
                <strong>{{ proposal.title|default:"your wedding/event service" }}</strong>.
              </p>

              <div style="border:1px solid #111111;padding:18px 20px;margin:24px 0;background:#fafafa;">
                <p style="margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:1px;color:#555555;">
                  Proposal Summary
                </p>
                <p style="margin:0;font-size:18px;font-weight:700;color:#111111;">
                  {{ proposal.title|default:"Wedding Service Proposal" }}
                </p>
                <p style="margin:8px 0 0;font-size:15px;">
                  Estimated Amount:
                  <strong>{{ proposal.total|default:"Please refer to the attached proposal" }}</strong>
                </p>
              </div>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Kindly review the proposal details. If a PDF proposal is attached, it will include the full
                service scope, pricing, and other relevant details.
              </p>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                If you have any questions or would like to request changes, please contact us at
                <a href="mailto:help@oceanclouds.in" style="color:#000000;font-weight:700;text-decoration:underline;">
                  help@oceanclouds.in
                </a>.
              </p>

              <p style="margin:28px 0 0;font-size:15px;line-height:1.7;">
                Warm regards,<br>
                <strong>{{ company_name }}</strong>
              </p>
            </td>
          </tr>

          <tr>
            <td style="background:#000000;color:#ffffff;padding:18px 32px;text-align:center;font-size:12px;line-height:1.6;">
              <p style="margin:0;">
                {{ company_name }} | Wedding & Event Services
              </p>
              <p style="margin:4px 0 0;">
                Need help? Contact help@oceanclouds.in
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</div>
        """.strip(),
        "body_text": """
Dear {{ client.name|default:"Client" }},

Thank you for considering {{ company_name }} for your special occasion.

We are pleased to share the proposal prepared for {{ proposal.title|default:"your wedding/event service" }}.

Proposal Amount: {{ proposal.total|default:"Please refer to the attached proposal" }}

Kindly review the proposal details. If a PDF proposal is attached, it will include the full service scope, pricing, and other relevant details.

For any questions or changes, please contact help@oceanclouds.in.

Warm regards,
{{ company_name }}
        """.strip(),
    },

    "contract": {
        "name": "Default Contract Email",
        "slug": "contract-default",
        "subject": "Wedding Service Contract from {{ company_name }} - {{ contract.number|default:'Contract' }}",
        "body_html": """
<div style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#111111;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:24px 0;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;background:#ffffff;border:1px solid #dddddd;">

          <tr>
            <td style="background:#000000;color:#ffffff;padding:28px 32px;text-align:center;">
              <h1 style="margin:0;font-size:26px;letter-spacing:1px;font-weight:700;">
                {{ company_name }}
              </h1>
              <p style="margin:8px 0 0;font-size:13px;letter-spacing:2px;text-transform:uppercase;">
                Wedding Service Agreement
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Dear {{ client.name|default:"Client" }},
              </p>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Greetings from <strong>{{ company_name }}</strong>.
              </p>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Your wedding/event service contract is ready for review and signature.
                Please review the agreement carefully before signing.
              </p>

              <div style="border:1px solid #111111;padding:18px 20px;margin:24px 0;background:#fafafa;">
                <p style="margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:1px;color:#555555;">
                  Contract Details
                </p>
                <p style="margin:0;font-size:18px;font-weight:700;color:#111111;">
                  Contract No: {{ contract.number|default:"-" }}
                </p>
                <p style="margin:8px 0 0;font-size:15px;">
                  Related Proposal:
                  <strong>{{ proposal.title|default:"-" }}</strong>
                </p>
              </div>

              {% if contract_signature_url %}
              <p style="margin:0 0 18px;font-size:15px;line-height:1.7;">
                To continue, please click the button below. The page will show the agreement and service details.
                Kindly scroll down, review the terms, and sign at the bottom.
              </p>

              <p style="text-align:center;margin:28px 0;">
                <a href="{{ contract_signature_url }}"
                   style="display:inline-block;background:#000000;color:#ffffff;text-decoration:none;padding:14px 26px;border-radius:0;font-size:14px;font-weight:700;letter-spacing:1px;text-transform:uppercase;">
                  Review & Sign Contract
                </a>
              </p>

              <p style="margin:0 0 16px;font-size:13px;line-height:1.7;color:#555555;">
                If the button does not work, copy and open this secure link:<br>
                <a href="{{ contract_signature_url }}" style="color:#000000;text-decoration:underline;word-break:break-all;">
                  {{ contract_signature_url }}
                </a>
              </p>
              {% else %}
              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                The contract signature link is currently unavailable. Please contact us for assistance.
              </p>
              {% endif %}

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                For any help regarding this contract, contact us at
                <a href="mailto:help@oceanclouds.in" style="color:#000000;font-weight:700;text-decoration:underline;">
                  help@oceanclouds.in
                </a>.
              </p>

              <p style="margin:28px 0 0;font-size:15px;line-height:1.7;">
                Warm regards,<br>
                <strong>{{ company_name }}</strong>
              </p>
            </td>
          </tr>

          <tr>
            <td style="background:#000000;color:#ffffff;padding:18px 32px;text-align:center;font-size:12px;line-height:1.6;">
              <p style="margin:0;">
                {{ company_name }} | Wedding & Event Services
              </p>
              <p style="margin:4px 0 0;">
                Need help? Contact help@oceanclouds.in
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</div>
        """.strip(),
        "body_text": """
Dear {{ client.name|default:"Client" }},

Greetings from {{ company_name }}.

Your wedding/event service contract is ready for review and signature.

Contract No: {{ contract.number|default:"-" }}
Related Proposal: {{ proposal.title|default:"-" }}

{% if contract_signature_url %}
Please review and sign your contract using this secure link:
{{ contract_signature_url }}

The page will show the agreement and service details. Please scroll down, review the terms, and sign at the bottom.
{% else %}
The contract signature link is currently unavailable. Please contact us for assistance.
{% endif %}

For any help, contact help@oceanclouds.in.

Warm regards,
{{ company_name }}
        """.strip(),
    },

    "invoice": {
        "name": "Default Invoice Email",
        "slug": "invoice-default",
        "subject": "Invoice {{ invoice.number|default:'Invoice' }} from {{ company_name }}",
        "body_html": """
<div style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#111111;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:24px 0;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;background:#ffffff;border:1px solid #dddddd;">

          <tr>
            <td style="background:#000000;color:#ffffff;padding:28px 32px;text-align:center;">
              <h1 style="margin:0;font-size:26px;letter-spacing:1px;font-weight:700;">
                {{ company_name }}
              </h1>
              <p style="margin:8px 0 0;font-size:13px;letter-spacing:2px;text-transform:uppercase;">
                Wedding & Event Invoice
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Dear {{ client.name|default:"Client" }},
              </p>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Please find your invoice details below for the confirmed wedding/event service.
              </p>

              <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:24px 0;border:1px solid #111111;">
                <tr>
                  <td style="padding:12px 14px;border-bottom:1px solid #dddddd;background:#fafafa;font-weight:700;">
                    Invoice Number
                  </td>
                  <td style="padding:12px 14px;border-bottom:1px solid #dddddd;text-align:right;">
                    {{ invoice.number|default:"-" }}
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 14px;border-bottom:1px solid #dddddd;background:#fafafa;font-weight:700;">
                    Total Amount
                  </td>
                  <td style="padding:12px 14px;border-bottom:1px solid #dddddd;text-align:right;">
                    {{ invoice.total|default:"-" }}
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 14px;background:#fafafa;font-weight:700;">
                    Due Date
                  </td>
                  <td style="padding:12px 14px;text-align:right;">
                    {{ invoice.due_date|default:"-" }}
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Kindly complete the payment on or before the due date. If a PDF invoice is attached,
                please refer to it for complete invoice details.
              </p>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                For payment-related assistance, contact us at
                <a href="mailto:help@oceanclouds.in" style="color:#000000;font-weight:700;text-decoration:underline;">
                  help@oceanclouds.in
                </a>.
              </p>

              <p style="margin:28px 0 0;font-size:15px;line-height:1.7;">
                Warm regards,<br>
                <strong>{{ company_name }}</strong>
              </p>
            </td>
          </tr>

          <tr>
            <td style="background:#000000;color:#ffffff;padding:18px 32px;text-align:center;font-size:12px;line-height:1.6;">
              <p style="margin:0;">
                {{ company_name }} | Wedding & Event Services
              </p>
              <p style="margin:4px 0 0;">
                Need help? Contact help@oceanclouds.in
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</div>
        """.strip(),
        "body_text": """
Dear {{ client.name|default:"Client" }},

Please find your invoice details below for the confirmed wedding/event service.

Invoice Number: {{ invoice.number|default:"-" }}
Total Amount: {{ invoice.total|default:"-" }}
Due Date: {{ invoice.due_date|default:"-" }}

Kindly complete the payment on or before the due date. If a PDF invoice is attached, please refer to it for complete invoice details.

For payment-related assistance, contact help@oceanclouds.in.

Warm regards,
{{ company_name }}
        """.strip(),
    },

    "payment": {
        "name": "Default Payment Receipt Email",
        "slug": "payment-default",
        "subject": "Payment Received by {{ company_name }}",
        "body_html": """
<div style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#111111;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:24px 0;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;background:#ffffff;border:1px solid #dddddd;">

          <tr>
            <td style="background:#000000;color:#ffffff;padding:28px 32px;text-align:center;">
              <h1 style="margin:0;font-size:26px;letter-spacing:1px;font-weight:700;">
                {{ company_name }}
              </h1>
              <p style="margin:8px 0 0;font-size:13px;letter-spacing:2px;text-transform:uppercase;">
                Payment Confirmation
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Dear {{ client.name|default:"Client" }},
              </p>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                Thank you. We have received your payment for the wedding/event service.
              </p>

              <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:24px 0;border:1px solid #111111;">
                <tr>
                  <td style="padding:12px 14px;border-bottom:1px solid #dddddd;background:#fafafa;font-weight:700;">
                    Amount Received
                  </td>
                  <td style="padding:12px 14px;border-bottom:1px solid #dddddd;text-align:right;">
                    {{ payment.amount|default:"-" }}
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 14px;border-bottom:1px solid #dddddd;background:#fafafa;font-weight:700;">
                    Payment Date
                  </td>
                  <td style="padding:12px 14px;border-bottom:1px solid #dddddd;text-align:right;">
                    {{ payment.date|default:"-" }}
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 14px;background:#fafafa;font-weight:700;">
                    Invoice
                  </td>
                  <td style="padding:12px 14px;text-align:right;">
                    {{ invoice.number|default:"-" }}
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                This email confirms that your payment has been recorded in our system.
              </p>

              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;">
                For any payment-related questions, contact us at
                <a href="mailto:help@oceanclouds.in" style="color:#000000;font-weight:700;text-decoration:underline;">
                  help@oceanclouds.in
                </a>.
              </p>

              <p style="margin:28px 0 0;font-size:15px;line-height:1.7;">
                Warm regards,<br>
                <strong>{{ company_name }}</strong>
              </p>
            </td>
          </tr>

          <tr>
            <td style="background:#000000;color:#ffffff;padding:18px 32px;text-align:center;font-size:12px;line-height:1.6;">
              <p style="margin:0;">
                {{ company_name }} | Wedding & Event Services
              </p>
              <p style="margin:4px 0 0;">
                Need help? Contact help@oceanclouds.in
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</div>
        """.strip(),
        "body_text": """
Dear {{ client.name|default:"Client" }},

Thank you. We have received your payment for the wedding/event service.

Amount Received: {{ payment.amount|default:"-" }}
Payment Date: {{ payment.date|default:"-" }}
Invoice: {{ invoice.number|default:"-" }}

This email confirms that your payment has been recorded in our system.

For any payment-related questions, contact help@oceanclouds.in.

Warm regards,
{{ company_name }}
        """.strip(),
    },
}


def get_template_owner(EmailTemplate):
    """
    If Owned.owner is required, assign first superuser/staff/user.
    If owner is nullable, returning None is okay.
    """
    try:
        owner_field = EmailTemplate._meta.get_field("owner")
    except Exception:
        return None

    User = get_user_model()

    owner = (
        User.objects.filter(is_superuser=True).first()
        or User.objects.filter(is_staff=True).first()
        or User.objects.first()
    )

    if owner:
        return owner

    if getattr(owner_field, "null", True):
        return None

    return None


def seed_default_email_templates(sender, **kwargs):
    EmailTemplate = apps.get_model("messaging", "EmailTemplate")

    owner = get_template_owner(EmailTemplate)

    for template_type, data in DEFAULT_EMAIL_TEMPLATES.items():
        # Only fill in a missing template. Never overwrite one that exists:
        # admins edit wording in the app and a deploy must not undo that.
        if EmailTemplate.objects.filter(type=template_type).exists():
            continue
        if EmailTemplate.objects.filter(slug=data["slug"]).exists():
            continue

        template_data = {
            "name": data["name"],
            "type": template_type,
            "subject": data["subject"],
            "body_html": data["body_html"],
            "body_text": data["body_text"],
            "is_active": True,
            "is_default_for_type": True,
            "attach_generated_pdf": template_type in ["proposal", "contract", "invoice", "payment"],
            "pdf_attachment_mode": EmailTemplate.PdfAttachmentMode.RELATED_OBJECT,
        }

        if owner and hasattr(EmailTemplate, "owner"):
            template_data["owner"] = owner

        template = EmailTemplate.objects.create(slug=data["slug"], **template_data)
        logger.info("Default email template created: %s", template.slug)


post_migrate.connect(
    seed_default_email_templates,
    sender=apps.get_app_config("messaging"),
    dispatch_uid="messaging_seed_default_email_templates",
)