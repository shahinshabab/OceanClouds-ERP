# ui/templatetags/sales_flow.py
"""
The sales journey tracker shown on lead, deal, proposal, contract and
invoice pages.

The flow is: inquiry -> lead -> deal -> proposal -> advance -> contract
(signed) -> approval, which creates the invoice, client and events. Existing customers can start at the
deal with a client already set, so the inquiry and lead steps show as
skipped for them.

Each step is "done", "current" (the next thing to do) or "todo"; the first
step that is not done carries the suggested next action.
"""

from django import template
from django.urls import reverse

from common.roles import can_access_sales

register = template.Library()


def _step(key, label, icon, state="todo", meta="", url="", action=None):
    return {
        "key": key,
        "label": label,
        "icon": icon,
        "state": state,
        "meta": meta,
        "url": url,
        "action": action,
    }


def _action(label, url, icon="bi-arrow-right", post=False, hint=""):
    return {"label": label, "url": url, "icon": icon, "post": post, "hint": hint}


def build_lead_flow(lead):
    """Flow for a lead that has no deal yet."""
    inquiry = lead.inquiry or lead.source_inquiries.order_by("created_at").first()
    steps = [
        _step(
            "inquiry", "Inquiry", "bi-inbox",
            "done" if inquiry else "skipped",
            inquiry.get_channel_display() if inquiry else "Direct lead",
            reverse("crm:inquiry_detail", args=[inquiry.pk]) if inquiry else "",
        ),
        _step("lead", "Lead", "bi-person-lines-fill", "done", lead.get_status_display(),
              reverse("crm:lead_detail", args=[lead.pk])),
        _step(
            "deal", "Deal", "bi-briefcase", "todo",
            action=_action("Convert to deal", reverse("sales:lead_convert_to_deal", args=[lead.pk]), "bi-briefcase"),
        ),
        _step("proposal", "Proposal", "bi-file-earmark-richtext"),
        _step("advance", "Advance", "bi-cash-coin"),
        _step("contract", "Contract", "bi-pen"),
        _step("approval", "Invoice & client", "bi-check2-circle"),
    ]
    return steps


def build_inquiry_flow(inquiry):
    """Flow for an inquiry that is not a lead yet."""
    return [
        _step("inquiry", "Inquiry", "bi-inbox", "done", inquiry.get_channel_display(),
              reverse("crm:inquiry_detail", args=[inquiry.pk])),
        _step(
            "lead", "Lead", "bi-person-lines-fill", "todo",
            action=_action("Convert to lead", reverse("crm:inquiry_convert_to_lead", args=[inquiry.pk]),
                           "bi-person-plus"),
        ),
        _step("deal", "Deal", "bi-briefcase"),
        _step("proposal", "Proposal", "bi-file-earmark-richtext"),
        _step("advance", "Advance", "bi-cash-coin"),
        _step("contract", "Contract", "bi-pen"),
        _step("approval", "Invoice & client", "bi-check2-circle"),
    ]


def build_deal_flow(deal):
    from sales.models import ContractStatus, ProposalStatus

    lead = deal.lead
    inquiry = None
    if lead:
        inquiry = lead.inquiry or lead.source_inquiries.order_by("created_at").first()
    existing_customer = bool(deal.client_id and not lead)

    proposals = list(deal.proposals.all().order_by("-created_at"))
    accepted = next((p for p in proposals if p.status == ProposalStatus.ACCEPTED), None)
    latest_proposal = accepted or (proposals[0] if proposals else None)

    contracts = list(deal.contracts.all().order_by("-created_at"))
    signed = next((c for c in contracts if c.status == ContractStatus.SIGNED), None)
    contract = signed or (contracts[0] if contracts else None)

    invoices = list(deal.invoices.all())
    final_invoices = [i for i in invoices if not i.is_advance]
    invoice = final_invoices[0] if final_invoices else None
    advance_paid = deal.advance_paid
    has_events = bool(contract and contract.events.exists())

    steps = []

    # Inquiry and lead
    if existing_customer:
        steps.append(_step("inquiry", "Inquiry", "bi-inbox", "skipped", "Existing customer"))
        steps.append(_step("lead", "Lead", "bi-person-lines-fill", "skipped", "Existing customer"))
    else:
        steps.append(_step(
            "inquiry", "Inquiry", "bi-inbox",
            "done" if inquiry else "skipped",
            inquiry.get_channel_display() if inquiry else "Direct lead",
            reverse("crm:inquiry_detail", args=[inquiry.pk]) if inquiry else "",
        ))
        steps.append(_step(
            "lead", "Lead", "bi-person-lines-fill",
            "done" if lead else "skipped",
            lead.name if lead else "",
            reverse("crm:lead_detail", args=[lead.pk]) if lead else "",
        ))

    steps.append(_step("deal", "Deal", "bi-briefcase", "done", deal.get_stage_display(),
                       reverse("sales:deal_detail", args=[deal.pk])))

    # Proposal
    new_proposal_url = reverse("sales:proposal_create") + f"?deal={deal.pk}"
    if accepted:
        steps.append(_step("proposal", "Proposal", "bi-file-earmark-richtext", "done", "Accepted",
                           reverse("sales:proposal_detail", args=[accepted.pk])))
    elif latest_proposal:
        steps.append(_step(
            "proposal", "Proposal", "bi-file-earmark-richtext", "todo",
            latest_proposal.get_status_display(),
            reverse("sales:proposal_detail", args=[latest_proposal.pk]),
            _action(
                "Open proposal to send or accept",
                reverse("sales:proposal_detail", args=[latest_proposal.pk]),
                "bi-file-earmark-richtext",
                hint=f"{latest_proposal.title} is {latest_proposal.get_status_display().lower()}.",
            ),
        ))
    else:
        steps.append(_step(
            "proposal", "Proposal", "bi-file-earmark-richtext", "todo", "Not created",
            action=_action("Create proposal", new_proposal_url, "bi-plus-lg"),
        ))

    # Advance
    if advance_paid > 0:
        steps.append(_step("advance", "Advance", "bi-cash-coin", "done", f"₹{advance_paid:,.0f} received"))
    else:
        steps.append(_step(
            "advance", "Advance", "bi-cash-coin", "todo", "Not received",
            action=_action(
                "Record advance",
                reverse("sales:deal_record_advance", args=[deal.pk]),
                "bi-cash-coin",
                hint="Booking advance is usually 10% of the accepted proposal.",
            ) if accepted else None,
        ))

    # Contract
    if signed:
        steps.append(_step("contract", "Contract", "bi-pen", "done",
                           f"Signed {signed.signed_date:%d %b}" if signed.signed_date else "Signed",
                           reverse("sales:contract_detail", args=[signed.pk])))
    elif contract:
        steps.append(_step(
            "contract", "Contract", "bi-pen", "todo", contract.get_status_display(),
            reverse("sales:contract_detail", args=[contract.pk]),
            _action(
                "Open contract to send for signing",
                reverse("sales:contract_detail", args=[contract.pk]),
                "bi-pen",
                hint=f"{contract.number or 'Contract'} is {contract.get_status_display().lower()}.",
            ),
        ))
    else:
        steps.append(_step(
            "contract", "Contract", "bi-pen", "todo", "Not created",
            action=_action(
                "Create contract",
                reverse("sales:proposal_convert_to_contract", args=[accepted.pk]),
                "bi-file-earmark-plus",
                hint="" if advance_paid > 0 else "No advance recorded yet.",
            ) if accepted else None,
        ))

    # Once the customer has signed, the earlier steps are settled even if
    # nobody updated them along the way.
    if signed:
        for step in steps:
            if step["key"] == "proposal" and step["state"] == "todo":
                step.update(state="done", action=None)
            elif step["key"] == "advance" and step["state"] == "todo":
                step.update(state="skipped", meta="None recorded", action=None)

    # Approval: a CRM manager approves the signed contract, which creates
    # the invoice, client and events.
    client_url = reverse("crm:client_detail", args=[deal.client_id]) if deal.client_id else ""
    invoice_url = reverse("sales:invoice_detail", args=[invoice.pk]) if invoice else ""
    if has_events or (existing_customer and invoice):
        steps.append(_step("approval", "Invoice & client", "bi-check2-circle", "done",
                           str(deal.client or "Approved"), invoice_url or client_url))
    elif signed and invoice:
        # Invoiced before approvals existed: only the client & events are left.
        steps.append(_step(
            "approval", "Invoice & client", "bi-check2-circle", "todo",
            "Invoice ready", invoice_url,
            _action(
                "Create client & events",
                reverse("sales:contract_create_client_event", args=[signed.pk]),
                "bi-people", post=True,
                hint="Creates the client from the lead and one event per contract day.",
            ),
        ))
    elif signed:
        steps.append(_step(
            "approval", "Invoice & client", "bi-check2-circle", "todo", "Waiting for approval",
            reverse("sales:contract_detail", args=[signed.pk]),
            _action(
                "Review and approve",
                reverse("sales:contract_detail", args=[signed.pk]) + "#approve",
                "bi-check2-circle",
                hint="Signed. A CRM manager approves to create the invoice and client.",
            ),
        ))
    else:
        steps.append(_step("approval", "Invoice & client", "bi-check2-circle", "todo", "After signing"))

    return steps


def build_status_controls(deal):
    """Status menus for the deal's latest proposal and contract."""
    from sales.models import ContractStatus, ProposalStatus

    controls = []
    proposal = deal.proposals.order_by("-created_at").first()
    if proposal:
        options = [
            {"value": value, "label": label, "url": reverse("sales:proposal_set_status", args=[proposal.pk])}
            for value, label in ProposalStatus.choices
            if value != ProposalStatus.ACCEPTED
        ]
        # Accepting also prices the deal, so it goes through its own view.
        options.insert(2, {"value": ProposalStatus.ACCEPTED, "label": ProposalStatus.ACCEPTED.label,
                           "url": reverse("sales:proposal_accept", args=[proposal.pk])})
        controls.append({"title": f"Proposal · {proposal.title}", "current": proposal.status, "options": options})

    contract = deal.contracts.order_by("-created_at").first()
    if contract:
        url = reverse("sales:contract_set_status", args=[contract.pk])
        controls.append({
            "title": f"Contract · {contract.number or 'draft'}",
            "current": contract.status,
            "options": [{"value": value, "label": label, "url": url} for value, label in ContractStatus.choices],
        })
    return controls


def _finalise(steps, user, current_key):
    first_open = next((s for s in steps if s["state"] == "todo"), None)
    if first_open:
        first_open["state"] = "current"
    for step in steps:
        step["is_here"] = step["key"] == current_key
    next_action = first_open["action"] if first_open else None
    if first_open and first_open["key"] == current_key and next_action and next_action["url"] == first_open["url"]:
        # The page itself is the next step; its own buttons carry the action.
        next_action = None
    if next_action and not can_access_sales(user):
        next_action = None
    done = sum(1 for s in steps if s["state"] in ("done", "skipped"))
    return {
        "steps": steps,
        "next": next_action,
        "next_step": first_open,
        "complete": first_open is None,
        "done_count": done,
        "count": len(steps),
    }


@register.inclusion_tag("ui/partials/sales_flow.html", takes_context=True)
def sales_flow(context, deal=None, lead=None, inquiry=None, here=""):
    request = context.get("request")
    user = getattr(request, "user", None)
    if deal is not None:
        steps = build_deal_flow(deal)
    elif lead is not None:
        deal = lead.deals.order_by("-created_at").first()
        steps = build_deal_flow(deal) if deal else build_lead_flow(lead)
    elif inquiry is not None:
        if inquiry.lead_id:
            return sales_flow(context, lead=inquiry.lead, here=here)
        if inquiry.status == "closed":
            return {"flow": None}
        steps = build_inquiry_flow(inquiry)
    else:
        return {"flow": None}
    flow = _finalise(steps, user, here)
    if deal is not None and user is not None and can_access_sales(user):
        flow["status_controls"] = build_status_controls(deal)
    return {
        "flow": flow,
        "csrf_token": context.get("csrf_token"),
        "here": here,
        "current_url": request.get_full_path() if request else "",
    }
