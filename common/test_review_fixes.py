"""Regression tests for the fixes from the October 2026 code review."""

from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from common.http import get_client_ip
from common.roles import ROLE_ADMIN, ROLE_EMPLOYEE
from common.test_helpers import make_user
from crm.models import Client
from events.models import Event
from messaging.models import EmailTemplate
from messaging.utils import render_email_from_template
from projects.models import (
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    WorkSession,
    WorkSessionStatus,
)
from sales.models import (
    Contract,
    ContractEventDay,
    ContractItem,
    Deal,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentType,
)
from services.models import Service
from todos.models import Todo


TODAY = timezone.localdate()


class NumberingTests(TestCase):
    def test_invoice_number_continues_past_999(self):
        deal = Deal.objects.create(name="Numbers")
        Invoice.objects.create(issue_date=TODAY, deal=deal, number="INV999")

        first = Invoice.objects.create(issue_date=TODAY, deal=deal)
        second = Invoice.objects.create(issue_date=TODAY, deal=deal)

        self.assertEqual(first.number, "INV1000")
        self.assertEqual(second.number, "INV1001")

    def test_service_code_continues_past_999(self):
        Service.objects.create(name="Old", code="SER999")
        self.assertEqual(Service.objects.create(name="New").code, "SER1000")


class PaymentTests(TestCase):
    def setUp(self):
        self.deal = Deal.objects.create(name="Pay")
        self.invoice = Invoice.objects.create(issue_date=TODAY, deal=self.deal, status=InvoiceStatus.ISSUED)
        Invoice.objects.filter(pk=self.invoice.pk).update(total=Decimal("1000"))
        self.invoice.refresh_from_db()

    def pay(self, amount, invoice=None, **kwargs):
        return Payment.objects.create(
            invoice=invoice or self.invoice,
            date=timezone.localdate(),
            amount=Decimal(amount),
            **kwargs,
        )

    def test_rejects_zero_and_negative_amounts(self):
        for amount in ("0", "-500"):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.pay(amount)

    def test_refund_reduces_amount_paid(self):
        self.pay("1000")
        self.pay("400", payment_type=PaymentType.REFUND)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("600"))
        self.assertEqual(self.invoice.status, InvoiceStatus.PARTIALLY_PAID)

    def test_refund_cannot_exceed_amount_paid(self):
        self.pay("300")
        with self.assertRaises(ValidationError):
            self.pay("500", payment_type=PaymentType.REFUND)

    def test_moving_payment_updates_both_invoices(self):
        other = Invoice.objects.create(issue_date=TODAY, deal=self.deal, status=InvoiceStatus.ISSUED)
        Invoice.objects.filter(pk=other.pk).update(total=Decimal("1000"))
        payment = self.pay("1000")

        payment.invoice = Invoice.objects.get(pk=other.pk)
        payment.save()

        self.invoice.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("0"))
        self.assertEqual(self.invoice.status, InvoiceStatus.ISSUED)
        self.assertEqual(other.amount_paid, Decimal("1000"))
        self.assertEqual(other.status, InvoiceStatus.PAID)


class SalesViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin", is_superuser=True)

    def setUp(self):
        self.client.force_login(self.admin)
        self.client_obj = Client.objects.create(name="Asha")
        self.deal = Deal.objects.create(name="Wedding", client=self.client_obj)
        self.contract = Contract.objects.create(deal=self.deal)
        day = ContractEventDay.objects.create(contract=self.contract, title="Wedding")
        ContractItem.objects.create(
            contract_event_day=day, description="Coverage", unit_price=Decimal("5000")
        )

    def invoice_post(self, **extra):
        data = {
            "deal": self.deal.pk,
            "issue_date": timezone.localdate().isoformat(),
            "due_date": timezone.localdate().isoformat(),
            "status": InvoiceStatus.DRAFT,
            "discount": "0",
            "tax_rate": "0",
            "notes": "",
        }
        data.update(extra)
        return self.client.post(reverse("sales:invoice_create"), data)

    def test_manual_invoice_does_not_copy_the_contract(self):
        self.invoice_post()
        invoice = Invoice.objects.get()
        self.assertIsNone(invoice.contract)
        self.assertEqual(invoice.items.count(), 0)

    def test_issued_invoice_from_contract_is_filled(self):
        response = self.invoice_post(contract=self.contract.pk, status=InvoiceStatus.ISSUED)

        invoice = Invoice.objects.get()
        self.assertRedirects(response, reverse("sales:invoice_detail", args=[invoice.pk]))
        self.assertEqual(invoice.status, InvoiceStatus.ISSUED)
        self.assertEqual(invoice.total, Decimal("5000"))

    def test_invoice_with_payments_cannot_be_deleted(self):
        invoice = Invoice.objects.create(issue_date=TODAY, deal=self.deal, status=InvoiceStatus.ISSUED)
        Invoice.objects.filter(pk=invoice.pk).update(total=Decimal("1000"))
        invoice.refresh_from_db()
        Payment.objects.create(invoice=invoice, date=timezone.localdate(), amount=Decimal("100"))

        for url in (
            reverse("sales:invoice_delete", args=[invoice.pk]),
            reverse("sales:deal_delete", args=[self.deal.pk]),
            reverse("crm:client_delete", args=[self.client_obj.pk]),
        ):
            with self.subTest(url=url):
                self.client.post(url)
                self.assertTrue(Payment.objects.exists())
                self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_payment_form_ignores_bad_invoice_parameter(self):
        response = self.client.get(reverse("sales:payment_create") + "?invoice=abc")
        self.assertEqual(response.status_code, 200)


class ClientIpTests(TestCase):
    def ip(self, forwarded_for="", remote="172.18.0.5"):
        request = RequestFactory().get(
            "/", HTTP_X_FORWARDED_FOR=forwarded_for, REMOTE_ADDR=remote
        )
        return get_client_ip(request)

    def test_ignores_client_supplied_entries(self):
        # client forged "1.2.3.4"; host Nginx appended the real 49.36.1.1;
        # the container Nginx appended the Docker gateway.
        self.assertEqual(self.ip("1.2.3.4, 49.36.1.1, 172.18.0.1"), "49.36.1.1")

    def test_invalid_values_are_skipped(self):
        self.assertEqual(self.ip("abc"), "172.18.0.5")


class NextUrlTests(TestCase):
    def render(self, value):
        return Template("{% load url_tags %}{{ value|local_url }}").render(
            Context({"value": value})
        )

    def test_only_local_paths_pass(self):
        self.assertEqual(self.render("/crm/clients/"), "/crm/clients/")
        for value in ("javascript:alert(1)", "https://evil.example", "//evil.example"):
            with self.subTest(value=value):
                self.assertEqual(self.render(value), "")


class ProjectFixTests(TestCase):
    def test_closed_project_can_still_be_edited(self):
        project = Project.objects.create(name="Done")
        project.status = ProjectStatus.COMPLETED
        project.save()
        project.status = ProjectStatus.CLOSED
        project.save()

        project.description = "Archived on the NAS"
        project.save()

    def test_pausing_an_ended_session_keeps_task_status(self):
        user = make_user("worker", is_superuser=True)
        project = Project.objects.create(name="Timer")
        task = Task.objects.create(project=project, name="Edit")
        session = WorkSession.objects.create(user=user, project=project, task=task)
        session.end()
        Task.objects.filter(pk=task.pk).update(status=TaskStatus.COMPLETED)

        self.client.force_login(user)
        response = self.client.post(reverse("projects:pause_work", args=[session.pk]))

        self.assertRedirects(response, reverse("projects:task_detail", args=[task.pk]))
        task.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(session.status, WorkSessionStatus.ENDED)


class EventUpdateTests(TestCase):
    def test_event_edit_saves_and_redirects(self):
        admin = make_user("boss", is_superuser=True)
        event = Event.objects.create(name="Haldi", date=timezone.localdate())
        self.client.force_login(admin)

        response = self.client.post(
            reverse("events:event_update", args=[event.pk]),
            {
                "name": "Haldi Night",
                "event_type": "wedding",
                "status": "planned",
                "date": timezone.localdate().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.name, "Haldi Night")


class AdminPanelAccessTests(TestCase):
    def test_staff_without_admin_role_is_refused(self):
        staff = make_user("staffer", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("adminpanel:user_edit", args=[staff.pk]))
        self.assertIn(response.status_code, (302, 403))

    def test_admin_role_cannot_grant_superuser(self):
        admin = make_user("office-admin", is_staff=False)
        admin.groups.add(Group.objects.get_or_create(name=ROLE_ADMIN)[0])
        self.client.force_login(admin)

        response = self.client.get(reverse("adminpanel:user_edit", args=[admin.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("is_superuser", response.context["form"].fields)


class TodoAccessTests(TestCase):
    def setUp(self):
        self.employee = make_user("editor", is_staff=False)
        self.employee.groups.add(Group.objects.get_or_create(name=ROLE_EMPLOYEE)[0])
        self.manager = make_user("pm", is_superuser=True)

    def test_employee_form_hides_sales_records(self):
        Deal.objects.create(name="Secret Deal")
        self.client.force_login(self.employee)
        form = self.client.get(reverse("todos:todo_create")).context["form"]
        self.assertFalse(form.fields["deal"].queryset.exists())
        self.assertFalse(form.fields["client"].queryset.exists())

    def test_employee_cannot_delete_assigned_todo(self):
        todo = Todo.objects.create(title="Edit film", owner=self.manager, assigned_to=self.employee)
        self.client.force_login(self.employee)
        response = self.client.post(reverse("todos:todo_delete", args=[todo.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Todo.objects.filter(pk=todo.pk).exists())


class EmailRenderingTests(TestCase):
    def test_subject_is_not_html_escaped_and_invoice_fields_render(self):
        template = EmailTemplate(
            name="Invoice",
            slug="invoice-test",
            type="invoice",
            subject="Invoice {{ invoice.number }} for {{ client.name }}",
            body_html="<p>{{ invoice.total }}</p>",
            body_text="Total {{ invoice.total }} for {{ client.name }}",
        )
        deal = Deal.objects.create(name="Mail")
        invoice = Invoice.objects.create(issue_date=TODAY, deal=deal)
        context = {"invoice": invoice, "client": {"name": "Ravi & Priya"}}

        subject, html, text = render_email_from_template(template, context)

        self.assertEqual(subject, f"Invoice {invoice.number} for Ravi & Priya")
        self.assertIn("Ravi & Priya", text)
