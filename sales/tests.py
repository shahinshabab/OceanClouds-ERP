from decimal import Decimal

from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from common.test_helpers import AuthenticatedViewTestMixin, make_user
from crm.models import Client, Lead
from events.models import Event
from services.models import Service, ServiceDeliverable

from .models import (
    Contract,
    ContractEventDay,
    ContractItem,
    Deal,
    DealStage,
    Invoice,
    InvoiceItem,
    InvoiceStatus,
    Payment,
    Proposal,
    ProposalEventDay,
    ProposalItem,
    ProposalPlan,
    ProposalStatus,
    ContractStatus,
    PaymentType,
)


class SalesTests(AuthenticatedViewTestMixin):
    list_url_names = [
        "sales:deal_list",
        "sales:proposal_list",
        "sales:contract_list",
        "sales:invoice_list",
        "sales:payment_list",
    ]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.client_obj = Client.objects.create(name="Sales Client")
        cls.deal = Deal.objects.create(name="Wedding Deal", client=cls.client_obj)

    def test_proposal_item_defaults_and_recalculates_totals(self):
        service = Service.objects.create(
            name="Wedding Film",
            base_price=Decimal("1500.00"),
        )
        ServiceDeliverable.objects.create(service=service, title="Highlight film")
        proposal = Proposal.objects.create(deal=self.deal, title="Proposal")
        plan = ProposalPlan.objects.create(proposal=proposal, name="Plan", tax_rate=18)
        event_day = ProposalEventDay.objects.create(plan=plan, title="Wedding")

        item = ProposalItem.objects.create(
            event_day=event_day,
            service=service,
            quantity=2,
        )
        plan.refresh_from_db()
        proposal.refresh_from_db()

        self.assertEqual(item.description, service.name)
        self.assertEqual(item.line_total, Decimal("3000.00"))
        self.assertEqual(item.deliverables.count(), 1)
        self.assertEqual(plan.total, Decimal("3540.00"))
        self.assertEqual(proposal.total, Decimal("3540.00"))

    def test_proposal_accept_plan_updates_deal(self):
        proposal = Proposal.objects.create(deal=self.deal, title="Accepted Proposal")
        plan = ProposalPlan.objects.create(
            proposal=proposal,
            name="Accepted Plan",
            total=Decimal("2000.00"),
        )

        proposal.accept_plan(plan)
        self.deal.refresh_from_db()

        self.assertEqual(proposal.status, ProposalStatus.ACCEPTED)
        # The deal is won only when the contract is signed.
        self.assertEqual(self.deal.stage, DealStage.NEGOTIATION)
        self.assertEqual(self.deal.amount, Decimal("2000.00"))

    def test_proposal_item_requires_service_or_package(self):
        proposal = Proposal.objects.create(deal=self.deal, title="Invalid Proposal")
        plan = ProposalPlan.objects.create(proposal=proposal, name="Plan")
        event_day = ProposalEventDay.objects.create(plan=plan, title="Wedding")

        with self.assertRaises(ValidationError):
            ProposalItem.objects.create(event_day=event_day)

    def test_contract_number_and_signing_token_are_generated(self):
        contract = Contract.objects.create(deal=self.deal)

        self.assertEqual(contract.number, "CTR001")
        self.assertIsNotNone(contract.signing_token)
        self.assertIn(str(contract.signing_token), contract.get_public_sign_path())

    def test_contract_item_recalculates_contract_total(self):
        contract = Contract.objects.create(deal=self.deal)
        event_day = ContractEventDay.objects.create(contract=contract, title="Wedding")

        ContractItem.objects.create(
            contract_event_day=event_day,
            description="Coverage",
            quantity=2,
            unit_price=Decimal("1200.00"),
        )
        contract.refresh_from_db()

        self.assertEqual(contract.total, Decimal("2400.00"))

    def test_invoice_item_and_payment_strings(self):
        invoice = Invoice.objects.create(
            deal=self.deal,
            issue_date=timezone.localdate(),
        )
        item = InvoiceItem.objects.create(
            invoice=invoice,
            description="Advance",
            quantity=1,
            unit_price=Decimal("500.00"),
        )
        invoice.status = InvoiceStatus.ISSUED
        invoice.save()
        payment = Payment.objects.create(
            invoice=invoice,
            amount=Decimal("500.00"),
            date=timezone.localdate(),
        )

        self.assertIn("Advance", str(item))
        self.assertIn("500.00", str(payment))


class ClientAfterContractFlowTests(TestCase):
    """
    Lead -> deal -> proposal -> advance -> contract signed -> invoice
    -> client + events. No client exists until the last step.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user(is_superuser=True)
        cls.service = Service.objects.create(name="Wedding Film", base_price=Decimal("10000.00"))

    def setUp(self):
        self.client.force_login(self.user)
        self.lead = Lead.objects.create(
            name="Anu & Rahul",
            email="anu@example.com",
            phone="9999999999",
            wedding_date=date(2026, 12, 20),
        )

    def _accepted_proposal(self, deal):
        proposal = Proposal.objects.create(deal=deal, title="Wedding Proposal")
        plan = ProposalPlan.objects.create(proposal=proposal, name="Plan")
        for day_date, title in [(date(2026, 12, 19), "Haldi"), (None, "Wedding")]:
            day = ProposalEventDay.objects.create(plan=plan, event_date=day_date, title=title, venue="Beach Hall")
            ProposalItem.objects.create(event_day=day, service=self.service, quantity=1)

        response = self.client.post(reverse("sales:proposal_accept", args=[proposal.pk]))
        self.assertEqual(response.status_code, 302)
        proposal.refresh_from_db()
        return proposal

    def test_full_flow_creates_client_only_after_signed_contract(self):
        response = self.client.post(
            reverse("sales:lead_convert_to_deal", args=[self.lead.pk]),
            {"name": "Anu Wedding", "lead": self.lead.pk, "stage": DealStage.NEW, "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        deal = Deal.objects.get(lead=self.lead)
        self.assertIsNone(deal.client)
        self.assertEqual(deal.customer.email, "anu@example.com")

        # Multiple proposals are fine; one gets accepted.
        Proposal.objects.create(deal=deal, title="First draft", version=5)
        proposal = self._accepted_proposal(deal)
        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.NEGOTIATION)
        self.assertFalse(Client.objects.exists())

        # Advance payment before the contract.
        response = self.client.get(reverse("sales:deal_record_advance", args=[deal.pk]))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("sales:deal_record_advance", args=[deal.pk]),
            {"amount": "2000.00", "date": "2026-10-03", "method": "upi", "reference": "UTR1", "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.ADVANCE_RECEIVED)
        advance_invoice = deal.invoices.get(is_advance=True)
        self.assertEqual(advance_invoice.status, InvoiceStatus.PAID)
        self.assertEqual(advance_invoice.payments.get().payment_type, PaymentType.ADVANCE)
        self.assertEqual(deal.advance_paid, Decimal("2000.00"))

        # Contract without a client.
        response = self.client.get(reverse("sales:proposal_convert_to_contract", args=[proposal.pk]))
        self.assertEqual(response.status_code, 200)
        contract = Contract.objects.create(deal=deal, owner=self.user)
        contract.populate_from_proposal(proposal, clear_existing=True)
        self.assertEqual(contract.total, Decimal("20000.00"))

        # Contract detail and PDF-free pages render with the lead as customer.
        for name in ["sales:contract_detail", "sales:proposal_detail", "sales:deal_detail"]:
            obj = {"sales:contract_detail": contract, "sales:proposal_detail": proposal, "sales:deal_detail": deal}[name]
            self.assertEqual(self.client.get(reverse(name, args=[obj.pk])).status_code, 200)
        public = self.client.get(reverse("sales:contract_public_sign", args=[contract.signing_token]))
        self.assertContains(public, "Anu &amp; Rahul")

        # Invoice is blocked until signed.
        response = self.client.get(reverse("sales:contract_generate_invoice", args=[contract.pk]))
        self.assertRedirects(response, reverse("sales:contract_detail", args=[contract.pk]))

        # Client signs.
        self.client.logout()
        self.client.post(
            reverse("sales:contract_public_sign", args=[contract.signing_token]),
            {"signed_by_name": "Anu", "accepted_terms": "on"},
        )
        self.client.force_login(self.user)
        contract.refresh_from_db()
        deal.refresh_from_db()
        self.assertEqual(contract.status, ContractStatus.SIGNED)
        self.assertEqual(deal.stage, DealStage.WON)
        self.assertFalse(Client.objects.exists())

        # Create client & event is blocked until the invoice exists.
        response = self.client.post(reverse("sales:contract_create_client_event", args=[contract.pk]))
        self.assertFalse(Client.objects.exists())

        response = self.client.post(
            reverse("sales:contract_generate_invoice", args=[contract.pk]),
            {
                "deal": deal.pk,
                "contract": contract.pk,
                "issue_date": "2026-10-03",
                "status": InvoiceStatus.DRAFT,
                "discount": "0",
                "tax_rate": "0",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        invoice = contract.invoices.get()
        self.assertEqual(invoice.advance_adjustment, Decimal("2000.00"))
        self.assertEqual(invoice.total, Decimal("18000.00"))
        self.assertEqual(invoice.gross_total, Decimal("20000.00"))
        self.assertEqual(self.client.get(reverse("sales:invoice_detail", args=[invoice.pk])).status_code, 200)

        response = self.client.post(reverse("sales:contract_create_client_event", args=[contract.pk]))
        client = Client.objects.get()
        self.assertRedirects(response, reverse("crm:client_detail", args=[client.pk]))
        deal.refresh_from_db()
        self.lead.refresh_from_db()
        self.assertEqual(deal.client, client)
        self.assertEqual(self.lead.client, client)
        self.assertEqual(self.lead.status, Lead.STATUS_CONVERTED_TO_CLIENT)
        self.assertEqual(client.email, "anu@example.com")
        self.assertTrue(client.contacts.filter(is_primary=True).exists())

        events = Event.objects.filter(contract=contract).order_by("date")
        self.assertEqual(events.count(), 2)
        # Day without its own date falls back to the lead's wedding date.
        self.assertEqual([e.date for e in events], [date(2026, 12, 19), date(2026, 12, 20)])
        self.assertTrue(all(e.client == client for e in events))
        self.assertEqual(list(events[0].services.all()), [self.service])

        # Running it again does not duplicate anything.
        self.client.post(reverse("sales:contract_create_client_event", args=[contract.pk]))
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Event.objects.filter(contract=contract).count(), 2)

    def test_existing_client_is_reused(self):
        existing = Client.objects.create(name="Anu", phone="9999999999")
        deal = Deal.objects.create(name="Anu Wedding", lead=self.lead)
        proposal = self._accepted_proposal(deal)
        contract = Contract.objects.create(deal=deal, status=ContractStatus.SIGNED)
        contract.populate_from_proposal(proposal, clear_existing=True)
        Invoice.objects.create(deal=deal, contract=contract, issue_date=timezone.localdate())

        self.client.post(reverse("sales:contract_create_client_event", args=[contract.pk]))

        deal.refresh_from_db()
        self.assertEqual(deal.client, existing)
        self.assertEqual(Client.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.email, "anu@example.com")

    def test_existing_customer_can_create_event_directly(self):
        existing = Client.objects.create(name="Old Customer")
        response = self.client.get(reverse("events:event_create") + f"?client={existing.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["client"], existing.pk)
