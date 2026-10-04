from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect
from django.utils import timezone

from crm.models import Client, Contact, Lead
from messaging.models import EmailTemplate

try:
    from num2words import num2words
except ImportError:
    num2words = None


def lead_status(name, fallback):
    return getattr(Lead, name, fallback)


def set_lead_status(lead, status_attr, fallback):
    if not lead:
        return

    lead.status = lead_status(status_attr, fallback)
    lead.save(update_fields=["status", "updated_at"])


def copy_lead_data_to_client_if_empty(client, lead):
    changed_fields = []

    lead_to_client_fields = [
        ("name", "name"),
        ("name", "display_name"),
        ("email", "email"),
        ("phone", "phone"),
        ("wedding_city", "city"),
        ("wedding_district", "district"),
        ("wedding_state", "state"),
        ("wedding_country", "country"),
    ]

    for lead_field, client_field in lead_to_client_fields:
        lead_value = getattr(lead, lead_field, None)
        if lead_value and not getattr(client, client_field, None):
            setattr(client, client_field, lead_value)
            changed_fields.append(client_field)

    if changed_fields:
        changed_fields.append("updated_at")
        client.save(update_fields=changed_fields)

    return client


def get_or_create_client_from_lead(lead, user):
    if lead.client_id:
        client = lead.client
        copy_lead_data_to_client_if_empty(client, lead)
        return client

    client = None

    if lead.email:
        client = Client.objects.filter(email__iexact=lead.email).first()

    if client is None and lead.phone:
        client = Client.objects.filter(phone__iexact=lead.phone).first()

    if client is None:
        client = Client.objects.create(
            owner=user,
            name=lead.name,
            display_name=lead.name,
            email=lead.email,
            phone=lead.phone or lead.whatsapp,
            city=lead.wedding_city,
            district=lead.wedding_district,
            state=lead.wedding_state or "Kerala",
            country=lead.wedding_country or "India",
            notes=f"Created from lead #{lead.pk}",
        )
    else:
        copy_lead_data_to_client_if_empty(client, lead)

    lead.client = client
    lead.save(update_fields=["client", "updated_at"])

    contact_match = Q(pk__in=[])
    if lead.email:
        contact_match |= Q(email__iexact=lead.email)
    if lead.phone:
        contact_match |= Q(phone__iexact=lead.phone)
    if lead.whatsapp:
        contact_match |= Q(whatsapp__iexact=lead.whatsapp)

    if lead.email or lead.phone or lead.whatsapp:
        existing_contact = client.contacts.filter(contact_match).first()

        if not existing_contact:
            Contact.objects.create(
                owner=user,
                client=client,
                first_name=lead.name or "Primary Contact",
                email=lead.email,
                phone=lead.phone,
                whatsapp=lead.whatsapp,
                is_primary=not client.contacts.filter(is_primary=True).exists(),
            )

    return client


def get_selected_proposal_plan(proposal):
    if hasattr(proposal, "get_pricing_plan"):
        return proposal.get_pricing_plan()

    if getattr(proposal, "accepted_plan_id", None):
        return proposal.accepted_plan

    primary_plan = proposal.plans.filter(is_primary=True).first()
    if primary_plan:
        return primary_plan

    return proposal.plans.order_by("sort_order", "id").first()


def get_pdf_event_days(plan):
    if not plan:
        return []

    return (
        plan.event_days.prefetch_related(
            "items",
            "items__service",
            "items__package",
            "items__deliverables",
        ).all()
    )


def get_proposal_client(proposal):
    if proposal.deal:
        return proposal.deal.customer

    return None


def get_amount_in_words(value):
    if num2words is None:
        return ""

    try:
        amount = int(Decimal(value or 0))
    except Exception:
        amount = 0

    if amount <= 0:
        return ""

    return f"{num2words(amount, lang='en_IN')} only"


# Payment split used everywhere (proposal terms, contract schedule, signing
# page, advance default). Change it here only.
ADVANCE_PERCENT = 10
EVENT_PERCENT = 30
DELIVERY_PERCENT = 60


def payment_split_term():
    return (
        f"{ADVANCE_PERCENT}% of the quoted amount should be paid in advance, "
        f"{EVENT_PERCENT}% on or the day after the function, "
        f"and the balance {DELIVERY_PERCENT}% upon delivery."
    )


def get_proposal_terms():
    return [
        payment_split_term(),
        "Additional charges for travel expense & accommodation if required.",
        "All prices are exclusive of taxes.",
        "Booking will be confirmed only after receiving the advance payment.",
        "The advance amount cannot be reimbursed in case of cancellation.",
        "Capture during the entire event can be accessed through a website or mobile link as a digital album.",
        "Photos for the signature albums, if included in the package, will be selected by the editors. Any add-ons should be mentioned prior to the post-production team.",
        "The soft copies for the signature albums will be shared with the clients and one set of corrections will be appreciable.",
        "The albums will be sent for printing on completion of final payment and delivery will be completed in 5-7 days from the date of payment.",
        "Any delay from the client's end will affect the workflow of the team and the promised delivery timeline.",
        "Ocean Clouds Wedding Company does not commit any client to post photos or videos of the event on its website or social networks. However, Ocean Clouds may upload the same for marketing purposes unless instructed otherwise.",
        "Any request to post photos or videos online will not be entertained at any cost.",
        "During the event, the client is responsible for local travel, food and accommodation. The room must be standard AC and fuel charges will be an additional cost.",
        "For every additional hour, there will be an extra charge of Rs. 1500 per camera.",
        "Any additional events not quoted will be charged extra.",
        "Any changes to the agreement must be made through a revised quote rather than a verbal agreement.",
        "All images and films are under the copyright of Ocean Clouds, which we may use for advertising and brand promotion.",
        "We are not liable for any losses caused by circumstances beyond our control, including natural disasters, power outages, technical difficulties, fire, or any other unforeseen occurrence that disrupts our service, including post-production.",
    ]


def percentage_amount(amount, percent):
    try:
        amount = Decimal(amount or 0)
        percent = Decimal(percent or 0)
    except Exception:
        return Decimal("0.00")

    return (amount * percent / Decimal("100")).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )


def get_contract_pdf_total(contract):
    for field_name in ["total", "total_amount", "amount", "contract_amount", "grand_total"]:
        value = getattr(contract, field_name, None)
        if value:
            try:
                return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            except Exception:
                pass

    if getattr(contract, "proposal", None):
        for field_name in ["total", "total_amount", "amount", "grand_total"]:
            value = getattr(contract.proposal, field_name, None)
            if value:
                try:
                    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                except Exception:
                    pass

    if getattr(contract, "deal", None):
        for field_name in ["value", "amount", "budget", "total"]:
            value = getattr(contract.deal, field_name, None)
            if value:
                try:
                    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                except Exception:
                    pass

    total = Decimal("0.00")

    try:
        for event_day in contract.event_days.all():
            for item in event_day.items.all():
                line_total = getattr(item, "line_total", None)
                if line_total:
                    total += Decimal(line_total)
                else:
                    quantity = Decimal(getattr(item, "quantity", 1) or 1)
                    unit_price = Decimal(getattr(item, "unit_price", 0) or 0)
                    total += quantity * unit_price
    except Exception:
        pass

    return total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


get_contract_public_sign_total = get_contract_pdf_total


def get_contract_client(contract):
    if getattr(contract, "deal", None):
        return contract.deal.customer

    return None


def get_oceanclouds_bank_details():
    return {
        "account_number": "0983073000000309",
        "account_holder": "OCEANCLOUDS PRODUCTION LLP",
        "ifsc_code": "SIBL0000983",
    }


def get_payment_plan_deliverable_rows():
    return [
        {
            "name": "PHOTO",
            "description": [
                "100 to 200 photos maximum depending on your package details. Photo gallery and reel will be delivered within 4 to 7 working days after the event.",
                "50 to 100 photos for each function depending on the function.",
            ],
        },
        {"name": "REEL", "description": ["30sec to 40sec portrait or landscape ratio."]},
        {
            "name": "WEDDING FILM / TEASER",
            "description": ["Between 1 minute to 5 minutes duration based on your video content."],
        },
        {
            "name": "HIGH LIGHT FILM",
            "description": [
                "Between 5 minutes to 10 minutes duration. The duration depends on the event timeline and video content."
            ],
        },
        {
            "name": "PRE WEDDING / POST WEDDING",
            "description": ["Reel or video. The duration of the film depends on the video content."],
        },
    ]


def get_payment_plan_client_notes():
    return [
        "We need a one hour section for bride/groom solo shoots.",
        "We need a one hour section for couple shoots.",
        "Photos of every function will be provided through Ocean Clouds photo gallery link.",
        "The photo gallery will be valid for up to 6 months.",
        "Wedding film is more like a short cinematic love story. It captures the essence of your main day, the key emotions, moments, rituals, and your bond as a couple.",
        "Highlight film is a more detailed edit. It includes candid moments, important parts of the function, rituals, and emotions, but not like a full documentary.",
        "If your package includes only wedding film and highlight film, full length documentary style coverage must be added separately.",
        "After the wedding/event, we will deliver the pen drive or drive link with your photos and films.",
        "The album design process will begin only after you provide selected photos for the album.",
        "For the safety of our equipment, we do not photograph or film events that use laser lights or trending laser effects.",
    ]


def get_payment_plan_terms():
    return [
        "All prices are exclusive of taxes.",
        "Booking will be confirmed only after receiving the advance payment.",
        "The advance amount cannot be reimbursed in case of cancellation.",
        payment_split_term(),
        "Additional charges for travel expense and accommodation will be applicable if required based on the distance and number of times we travel.",
        "Our charges are for the reserved time and crew availability, not solely for the number of photos or videos delivered.",
        "If, for any reason, the shoot cannot be carried out as scheduled due to delays, cancellations, or circumstances beyond our control, the agreed payment remains payable in full.",
        "The post production work will begin only after completion of the second payment and any delay in payment will affect the promised date of submission of outputs.",
        "The raw files will only be delivered after completion of final payment.",
        "The album will be sent for printing only after completion of final payment and the delivery will be completed within 7 to 10 working days from the date of payment.",
        "Two sets of correction for highlight film will be appreciable, unless it is a miss out from the team and the same applies for documentary videos.",
        "The events will be captured according to the plan that we have already discussed. Any changes in concept should be informed before the event.",
        "The edited photos will be selected completely under our direction.",
        "Photos for the signature album, if included in the package, will be selected by the editors. Any add-ons should be mentioned prior to the post production team.",
        "The soft copies for the signature album will be shared with the clients and one set of corrections will be appreciable.",
        "Any delay from the client's end will affect the entire workflow of the team and the timelines we promise to deliver the output.",
        "We do not commit any client to post photos or videos of the event on our website or social networks. However, we may upload the same for marketing purposes unless instructed otherwise.",
        "Any request to post the photos or videos online will not be entertained at any cost.",
        "Lighting requirements that we have from our end depend on the location and time of day.",
        "Any additional events not quoted will be charged extra.",
        "Any changes to the agreement must be made through a revised quote rather than a verbal agreement.",
        "We are not liable for any losses caused by circumstances beyond our control, including natural disasters, power outages, technical difficulties, fire, or any other unforeseen occurrence that disrupts our service.",
    ]


def get_payment_plan_important_terms():
    return [
        "While we acknowledge that events can be both enjoyable and hectic, everyone should adhere to the designated timelines. Sufficient time is required for comprehensive coverage and creative work.",
        "The company cannot be held responsible for restrictions imposed by the venue, including flash, photography, drones, laser areas, or other restrictions. The client should communicate such things to the company beforehand or negotiate with the venue coordinators.",
    ]


def email_enabled():
    return bool(getattr(settings, "EMAIL_SENDING_ENABLED", False))


def get_active_email_template(template_type):
    return (
        EmailTemplate.objects.filter(type=template_type, is_active=True)
        .order_by("-is_default_for_type", "name")
        .first()
    )


def resolve_client_email(client):
    if not client:
        return ""

    email = (getattr(client, "email", "") or "").strip()
    if email:
        return email

    # Deals without a client yet use the lead's details (LeadCustomer).
    if not isinstance(client, Client):
        return ""

    primary = getattr(client, "primary_contact", None)
    if primary:
        primary_email = (getattr(primary, "email", "") or "").strip()
        if primary_email:
            return primary_email

    contact = client.contacts.exclude(email="").first()
    if contact:
        return (contact.email or "").strip()

    return ""


def resolve_primary_contact(client):
    if not client or not isinstance(client, Client):
        return None

    primary = getattr(client, "primary_contact", None)
    if primary:
        return primary

    return client.contacts.exclude(email="").first()


def build_common_email_context(*, client=None, contact=None, deal=None):
    return {
        "company_name": "Ocean Clouds",
        "client": client,
        "contact": contact,
        "deal": deal,
        "today": timezone.localdate(),
        "now": timezone.now(),
    }


def flash_send_result(request, label, to_email, result, success_tags=""):
    if getattr(result, "ok", False):
        messages.success(
            request,
            f"{label} email sent successfully to {to_email}.",
            extra_tags=success_tags,
        )
        return

    error_msg = getattr(result, "error", "") or "Email could not be sent."

    if "disabled" in error_msg.lower():
        messages.warning(
            request,
            f"{label} email was not sent because email sending is disabled in settings.",
            extra_tags=success_tags,
        )
    elif "no active template" in error_msg.lower():
        messages.warning(
            request,
            f"No active {label.lower()} email template found. Please create or activate one template first.",
            extra_tags=success_tags,
        )
    else:
        messages.error(
            request,
            f"{label} email failed: {error_msg}",
            extra_tags=success_tags,
        )


def check_before_send(
    request,
    *,
    template_type,
    label,
    to_email,
    redirect_url_name,
    redirect_pk,
    object_scope,
    scope_tags,
):
    message_tags = scope_tags(object_scope, "email")

    if not email_enabled():
        messages.warning(
            request,
            f"{label} email was not sent because EMAIL_SENDING_ENABLED is False.",
            extra_tags=message_tags,
        )
        return redirect(redirect_url_name, pk=redirect_pk)

    if not to_email:
        messages.error(
            request,
            "Client email not found. Please add client email or primary contact email.",
            extra_tags=message_tags,
        )
        return redirect(redirect_url_name, pk=redirect_pk)

    template = get_active_email_template(template_type)
    if not template:
        messages.warning(
            request,
            f"No active {label.lower()} email template found. Please create one in Messaging > Templates.",
            extra_tags=message_tags,
        )
        return redirect(redirect_url_name, pk=redirect_pk)

    return None


def _event_date_for_day(contract, day=None):
    deal = contract.deal
    lead = deal.lead if deal else None

    return (
        (day.event_date if day else None)
        or contract.start_date
        or (lead.wedding_date if lead else None)
        or (deal.expected_close_date if deal else None)
    )


def create_client_and_events_from_contract(contract, user):
    """
    Final step of the sales flow, after the contract is signed and invoiced.

    - Creates the client from the lead (or reuses one with the same
      email/phone), links it to the deal and lead, and adds a primary contact.
    - Creates one event per contract event day, carrying over its services
      and packages. Events already created from this contract are kept.

    Returns (client, created_events, skipped_day_titles).
    """

    from events.models import Event, EventStatus, Venue

    deal = contract.deal
    lead = deal.lead

    if deal.client_id:
        client = deal.client
        if lead:
            copy_lead_data_to_client_if_empty(client, lead)
            if not lead.client_id:
                lead.client = client
                lead.save(update_fields=["client", "updated_at"])
    elif lead:
        client = get_or_create_client_from_lead(lead, user)
    else:
        client = Client.objects.create(
            owner=user,
            name=deal.name,
            display_name=deal.name,
            notes=f"Created from contract {contract.number}",
        )

    if deal.client_id != client.pk:
        deal.client = client
        deal.save(update_fields=["client", "updated_at"])

    if lead:
        set_lead_status(lead, "STATUS_CONVERTED_TO_CLIENT", "converted_to_client")

    primary_contact = client.primary_contact or client.contacts.first()

    created_events = []
    skipped_days = []

    if contract.events.exists():
        return client, created_events, skipped_days

    days = list(
        contract.event_days.prefetch_related(
            "items__service",
            "items__package",
        ).all()
    )

    for day in days:
        event_date = _event_date_for_day(contract, day)
        if not event_date:
            skipped_days.append(day.title)
            continue

        venue = None
        if day.venue:
            venue = Venue.objects.filter(name__iexact=day.venue.strip()).first()

        notes = [line for line in [
            f"Venue: {day.venue}" if day.venue and not venue else "",
            day.notes,
        ] if line]

        event = Event.objects.create(
            owner=user,
            client=client,
            primary_contact=primary_contact,
            contract=contract,
            name=f"{client} - {day.title}",
            status=EventStatus.CONFIRMED,
            date=event_date,
            start_time=day.start_time,
            end_time=day.end_time,
            venue=venue,
            notes="\n".join(notes),
            internal_notes=f"Created from signed contract {contract.number}.",
        )

        services = {item.service for item in day.items.all() if item.service_id}
        packages = {item.package for item in day.items.all() if item.package_id}
        if services:
            event.services.set(services)
        if packages:
            event.packages.set(packages)

        event.sync_auto_checklist(owner=user)
        created_events.append(event)

    if not days:
        event_date = _event_date_for_day(contract)
        if event_date:
            event = Event.objects.create(
                owner=user,
                client=client,
                primary_contact=primary_contact,
                contract=contract,
                name=f"{client} - Wedding",
                status=EventStatus.CONFIRMED,
                date=event_date,
                internal_notes=f"Created from signed contract {contract.number}.",
            )
            event.sync_auto_checklist(owner=user)
            created_events.append(event)
        else:
            skipped_days.append("Wedding")

    return client, created_events, skipped_days


# ============================================================
# Proposal / contract documents (HTML -> PDF)
# ============================================================

def _clean_lines(text):
    return [line.strip(" -•\t") for line in str(text or "").splitlines() if line.strip(" -•\t")]


def _deliverable_rows(days):
    """
    One row per deliverable across all event days, quantities added up.
    "1 item" is left out because it says nothing.
    """
    grouped = {}

    for day in days:
        for item in day.items.all():
            for deliverable in item.deliverables.all():
                if not getattr(deliverable, "is_included", True):
                    continue
                title = (deliverable.title or "").strip()
                if not title:
                    continue
                unit = deliverable.unit or ""
                row = grouped.setdefault(
                    (title.lower(), unit),
                    {"title": title, "quantity": Decimal("0"), "unit_code": unit,
                     "unit": deliverable.get_unit_display() if unit else ""},
                )
                row["quantity"] += Decimal(deliverable.quantity or 0)

    rows = []
    for row in grouped.values():
        if row["unit_code"] in ("item", "") and row["quantity"] == 1:
            row["quantity"] = None
            row["unit"] = ""
        elif row["unit_code"] in ("item", "other"):
            row["unit"] = ""
        elif row["unit"] and row["quantity"] != 1:
            row["unit"] = f"{row['unit']}s"
        rows.append(row)
    return rows


def _date_span(days):
    dates = sorted(day.event_date for day in days if day.event_date)
    if not dates:
        return None, None
    return dates[0], dates[-1]


def proposal_reference(proposal):
    return f"OC-P{proposal.pk:04d}-V{proposal.version or 1}"


def build_proposal_document_context(proposal):
    plan = get_selected_proposal_plan(proposal)
    days = list(get_pdf_event_days(plan)) if plan else []
    first_date, last_date = _date_span(days)
    customer = get_proposal_client(proposal)

    return {
        "proposal": proposal,
        "client": customer,
        "city": getattr(customer, "city", "") if customer else "",
        "selected_plan": plan,
        "event_days": days,
        "deliverables": _deliverable_rows(days),
        "first_date": first_date,
        "last_date": last_date,
        "reference": proposal_reference(proposal),
        "amount_words": get_amount_in_words(plan.total if plan else proposal.total),
        "terms": _clean_lines(proposal.terms) or get_proposal_terms(),
    }


PAYMENT_SCHEDULE = (
    ("Booking advance", ADVANCE_PERCENT, "To reserve your dates"),
    ("On the event day", EVENT_PERCENT, "On or the day after the function"),
    ("On delivery", DELIVERY_PERCENT, "When the final outputs are delivered"),
)


def build_contract_document_context(contract):
    days = list(
        contract.event_days.prefetch_related(
            "items", "items__service", "items__package", "items__deliverables"
        ).all()
    )
    first_date, last_date = _date_span(days)
    total = get_contract_pdf_total(contract)

    payments = []
    remaining = total
    for index, (label, percent, note) in enumerate(PAYMENT_SCHEDULE):
        amount = remaining if index == len(PAYMENT_SCHEDULE) - 1 else percentage_amount(total, percent)
        remaining -= amount
        payments.append({"label": label, "percent": percent, "note": note, "amount": amount})

    terms = _clean_lines(contract.terms) or get_payment_plan_terms()
    client_notes = get_payment_plan_client_notes()
    important_terms = get_payment_plan_important_terms()

    return {
        "contract": contract,
        # Views showing the contract to production staff turn this off.
        "show_money": True,
        "client": get_contract_client(contract),
        "event_days": days,
        "deliverables": _deliverable_rows(days),
        "first_date": first_date,
        "last_date": last_date,
        "total_amount": total,
        "amount_words": get_amount_in_words(total),
        "payments": payments,
        "advance_paid": contract.deal.advance_paid if contract.deal_id else Decimal("0"),
        "bank_details": get_oceanclouds_bank_details(),
        "deliverable_rows": get_payment_plan_deliverable_rows(),
        "client_notes": client_notes,
        "terms": terms,
        "important_terms": important_terms,
        "all_terms": terms + client_notes[4:] + important_terms,
    }
