from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from common.roles import ROLE_CRM_MANAGER, ROLE_EMPLOYEE, ROLE_PROJECT_MANAGER
from common.test_helpers import AuthenticatedViewTestMixin, make_user
from crm.models import Client, Contact
from projects.models import Project
from services.models import InventoryItem, Service, Vendor

from .forms import EventForm
from .models import ChecklistItem, Event, EventChecklist, Venue


class EventsTests(AuthenticatedViewTestMixin):
    list_url_names = [
        "events:event_calendar",
        "events:venue_list",
        "events:event_list",
        "events:checklist_list",
    ]

    def test_venue_and_event_strings(self):
        venue = Venue.objects.create(name="Ocean Hall")
        event = Event.objects.create(
            name="Wedding",
            date=timezone.localdate(),
            venue=venue,
        )

        self.assertEqual(str(venue), "Ocean Hall")
        self.assertIn("Wedding", str(event))

    def test_event_checklist_is_created_and_counts_items(self):
        event = Event.objects.create(name="Reception", date=timezone.localdate())
        checklist = event.checklist
        ChecklistItem.objects.create(checklist=checklist, title="Call client")
        ChecklistItem.objects.create(checklist=checklist, title="Book crew", is_done=True)

        self.assertEqual(event.checklist_total, 2)
        self.assertEqual(event.checklist_done_count, 1)
        self.assertEqual(event.checklist_pending_count, 1)

    def test_sync_auto_checklist_adds_related_items_once(self):
        venue = Venue.objects.create(name="Beach Venue")
        service = Service.objects.create(name="Photography")
        vendor = Vendor.objects.create(name="Main Shooter")
        inventory = InventoryItem.objects.create(
            name="Camera",
            quantity_total=2,
            quantity_available=2,
        )
        event = Event.objects.create(
            name="Wedding",
            date=timezone.localdate(),
            venue=venue,
        )
        event.services.add(service)
        event.vendors.add(vendor)
        event.inventory_items.add(inventory)

        event.sync_auto_checklist()
        first_count = event.checklist.items.count()
        event.sync_auto_checklist()

        self.assertEqual(event.checklist.items.count(), first_count)
        self.assertGreaterEqual(first_count, 4)

    def test_checklist_item_string_and_event_property(self):
        event = Event.objects.create(name="Haldi", date=timezone.localdate())
        checklist = EventChecklist.objects.create(event=event, title="Haldi Checklist")
        item = ChecklistItem.objects.create(checklist=checklist, title="Decor")

        self.assertEqual(item.event, event)
        self.assertIn("Decor", str(item))

    def test_event_form_rejects_end_time_before_start_time(self):
        form = EventForm(
            data={
                "client": "",
                "name": "Wedding",
                "event_type": "wedding",
                "status": "planned",
                "date": timezone.localdate(),
                "start_time": "12:00",
                "end_time": "11:00",
                "venue": "",
                "services": [],
                "packages": [],
                "vendors": [],
                "inventory_items": [],
                "notes": "",
                "internal_notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("end_time", form.errors)


class EventWithoutProjectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("boss", is_superuser=True)
        cls.client_obj = Client.objects.create(name="Anu")
        cls.contact = Contact.objects.create(
            client=cls.client_obj,
            first_name="Anu",
            phone="9999999999",
            is_primary=True,
        )

    def _user_in(self, username, role=None):
        user = make_user(username, is_staff=False)
        if role:
            user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def test_event_is_created_without_project_contact_vendors_or_inventory(self):
        self.client.force_login(self.admin)

        form_page = self.client.get(reverse("events:event_create"))
        for field in ("project", "primary_contact", "vendors", "inventory_items"):
            self.assertNotIn(field, form_page.context["form"].fields)

        response = self.client.post(
            reverse("events:event_create"),
            {
                "client": self.client_obj.pk,
                "name": "Anu - Wedding",
                "event_type": "wedding",
                "status": "planned",
                "date": timezone.localdate().isoformat(),
            },
        )

        event = Event.objects.get(name="Anu - Wedding")
        self.assertRedirects(response, event.get_absolute_url())
        self.assertIsNone(event.project)
        self.assertIsNone(event.primary_contact)
        self.assertEqual(event.contact, self.contact)

    def test_edit_form_still_offers_vendors_and_inventory(self):
        event = Event.objects.create(name="Haldi", date=timezone.localdate())
        self.client.force_login(self.admin)

        response = self.client.get(reverse("events:event_update", args=[event.pk]))

        self.assertIn("vendors", response.context["form"].fields)
        self.assertIn("inventory_items", response.context["form"].fields)

    def test_all_managers_can_manage_events(self):
        for role in (ROLE_CRM_MANAGER, ROLE_PROJECT_MANAGER):
            with self.subTest(role=role):
                self.client.force_login(self._user_in(f"user-{role}", role))
                self.assertEqual(self.client.get(reverse("events:event_list")).status_code, 200)
                self.assertEqual(self.client.get(reverse("events:event_create")).status_code, 200)

    def test_employee_cannot_manage_events(self):
        self.client.force_login(self._user_in("emp", ROLE_EMPLOYEE))
        self.assertEqual(self.client.get(reverse("events:event_list")).status_code, 403)

    def test_everyone_can_see_calendar(self):
        for role in (ROLE_CRM_MANAGER, ROLE_PROJECT_MANAGER, ROLE_EMPLOYEE, None):
            with self.subTest(role=role):
                self.client.force_login(self._user_in(f"cal-{role}", role))
                self.assertEqual(self.client.get(reverse("events:event_calendar")).status_code, 200)

    def test_project_is_created_from_event(self):
        event = Event.objects.create(
            name="Anu - Wedding",
            client=self.client_obj,
            date=timezone.localdate(),
        )
        self.client.force_login(self.admin)

        detail = self.client.get(event.get_absolute_url())
        create_url = reverse("projects:project_create") + f"?event={event.pk}"
        self.assertContains(detail, create_url)

        form_page = self.client.get(create_url)
        initial = form_page.context["form"].initial
        self.assertEqual(initial["events"], [event.pk])
        self.assertEqual(initial["client"], self.client_obj.pk)

        self.client.post(
            create_url,
            {
                "name": "Anu - Wedding",
                "client": self.client_obj.pk,
                "events": [event.pk],
                "status": "planned",
                "priority": "medium",
            },
        )

        project = Project.objects.get(name="Anu - Wedding")
        event.refresh_from_db()
        self.assertEqual(event.project, project)
        self.assertEqual(event.linked_project, project)
