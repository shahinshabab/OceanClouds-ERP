# messaging/services.py

from django.utils import timezone

from .models import EmailTemplate, Campaign, CampaignRecipient, WhatsAppTemplate
from .utils import send_templated_email, send_templated_whatsapp

def get_client_email(client):
    """
    Tries to get primary email from client or first contact.
    Adjust this based on your actual Client/Contact model.
    """

    if not client:
        return ""

    if getattr(client, "email", None):
        return client.email

    contacts = getattr(client, "contacts", None)

    if contacts:
        contact = contacts.exclude(email="").first()
        if contact:
            return contact.email

    return ""


def get_common_context(*, client=None, contact=None, related_object=None):
    return {
        "company_name": "Ocean Clouds",
        "client": client,
        "contact": contact,
        "object": related_object,
        "today": timezone.localdate(),
        "now": timezone.now(),
    }


def send_proposal_email(proposal, generated_pdf=None):
    client = getattr(proposal, "client", None)

    if not client and getattr(proposal, "deal", None):
        client = getattr(proposal.deal, "client", None)

    to_email = get_client_email(client)

    context = get_common_context(
        client=client,
        related_object=proposal,
    )
    context["proposal"] = proposal

    return send_templated_email(
        template_type=EmailTemplate.TemplateType.PROPOSAL,
        to_emails=to_email,
        context=context,
        related_object=proposal,
        generated_pdf=generated_pdf,
    )


def send_contract_email(contract, generated_pdf=None):
    client = getattr(contract, "client", None)

    if not client and getattr(contract, "deal", None):
        client = getattr(contract.deal, "client", None)

    to_email = get_client_email(client)

    context = get_common_context(
        client=client,
        related_object=contract,
    )
    context["contract"] = contract

    return send_templated_email(
        template_type=EmailTemplate.TemplateType.CONTRACT,
        to_emails=to_email,
        context=context,
        related_object=contract,
        generated_pdf=generated_pdf,
    )


def send_invoice_email(invoice, generated_pdf=None):
    client = getattr(invoice, "client", None)

    if not client and getattr(invoice, "contract", None):
        client = getattr(invoice.contract, "client", None)

    to_email = get_client_email(client)

    context = get_common_context(
        client=client,
        related_object=invoice,
    )
    context["invoice"] = invoice

    return send_templated_email(
        template_type=EmailTemplate.TemplateType.INVOICE,
        to_emails=to_email,
        context=context,
        related_object=invoice,
        generated_pdf=generated_pdf,
    )


def send_payment_email(payment, generated_pdf=None):
    invoice = getattr(payment, "invoice", None)
    client = getattr(invoice, "client", None) if invoice else None

    to_email = get_client_email(client)

    context = get_common_context(
        client=client,
        related_object=payment,
    )
    context["payment"] = payment
    context["invoice"] = invoice

    return send_templated_email(
        template_type=EmailTemplate.TemplateType.PAYMENT,
        to_emails=to_email,
        context=context,
        related_object=payment,
        generated_pdf=generated_pdf,
    )


def send_anniversary_email(contact, client=None):
    to_email = getattr(contact, "email", "")

    context = get_common_context(
        client=client,
        contact=contact,
        related_object=contact,
    )

    return send_templated_email(
        template_type=EmailTemplate.TemplateType.ANNIVERSARY,
        to_emails=to_email,
        context=context,
        related_object=contact,
    )


def sync_campaign_recipients(campaign):
    """
    No custom pasted list.
    Only CRM contacts with allow_marketing=True.
    """

    from crm.models import Contact

    campaign.recipients.exclude(
        status=CampaignRecipient.SendStatus.SENT
    ).delete()

    contact_qs = Contact.objects.exclude(email="").filter(
        allow_marketing=True,
    )

    if campaign.target_type == Campaign.TargetType.ANNIVERSARY:
        contact_qs = contact_qs.filter(
            role__in=["bride", "groom"]
        )

    new_rows = []

    for contact in contact_qs.select_related("client"):
        email = (contact.email or "").strip().lower()

        if not email:
            continue

        client = getattr(contact, "client", None)

        new_rows.append(
            CampaignRecipient(
                campaign=campaign,
                email=email,
                first_name=getattr(contact, "first_name", "") or "",
                last_name=getattr(contact, "last_name", "") or "",
                company=str(client) if client else "",
                client_id=getattr(client, "pk", None),
                contact_id=getattr(contact, "pk", None),
                status=CampaignRecipient.SendStatus.PENDING,
            )
        )

    if new_rows:
        CampaignRecipient.objects.bulk_create(
            new_rows,
            ignore_conflicts=True,
        )



def get_client_whatsapp(client):
    if not client:
        return ""

    if getattr(client, "phone", None):
        return client.phone

    contacts = getattr(client, "contacts", None)

    if contacts:
        contact = contacts.exclude(whatsapp="").first()
        if contact:
            return contact.whatsapp

        contact = contacts.exclude(phone="").first()
        if contact:
            return contact.phone

    return ""


def get_vendor_whatsapp(vendor):
    if not vendor:
        return ""

    return (
        getattr(vendor, "whatsapp", "")
        or getattr(vendor, "phone", "")
        or getattr(vendor, "alt_phone", "")
        or ""
    )


def get_event_whatsapp_context(event):
    context = {
        "company_name": "Ocean Clouds",
        "event": event,
        "project": getattr(event, "project", None),
        "client": getattr(event, "client", None),
        "primary_contact": getattr(event, "primary_contact", None),
        "venue": getattr(event, "venue", None),
        "services": event.services.all(),
        "packages": event.packages.all(),
        "vendors": event.vendors.all(),
        "inventory_items": event.inventory_items.all(),
        "today": timezone.localdate(),
        "now": timezone.now(),
    }

    return context


def send_event_client_whatsapp(event):
    client = getattr(event, "client", None)
    to_number = get_client_whatsapp(client)

    context = get_event_whatsapp_context(event)

    return send_templated_whatsapp(
        template_type=WhatsAppTemplate.TemplateType.EVENT_CLIENT,
        to_number=to_number,
        context=context,
        related_object=event,
    )


def send_event_vendor_whatsapp(event, vendor):
    to_number = get_vendor_whatsapp(vendor)

    context = get_event_whatsapp_context(event)
    context["vendor"] = vendor

    return send_templated_whatsapp(
        template_type=WhatsAppTemplate.TemplateType.EVENT_VENDOR,
        to_number=to_number,
        context=context,
        related_object=event,
    )


def send_event_all_vendor_whatsapp(event):
    results = []

    for vendor in event.vendors.all():
        result = send_event_vendor_whatsapp(event, vendor)
        results.append((vendor, result))

    return results