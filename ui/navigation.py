# ui/navigation.py
"""
Sidebar navigation.

The groups follow the order work moves through the business: a sale runs
inquiry -> lead -> deal -> proposal -> advance -> contract -> invoice, and
only then becomes a client with events and production work. Contacts and
reviews live inside the client page, so they have no sidebar entry.

Each item names the roles that may see it (None = every signed-in user)
and the URL prefixes that should keep it highlighted on detail, edit and
create pages.
"""

from django.urls import NoReverseMatch, reverse

from common.roles import (
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_EMPLOYEE,
    ROLE_PROJECT_MANAGER,
)

ADMIN = {ROLE_ADMIN}
SALES = {ROLE_ADMIN, ROLE_CRM_MANAGER}
PROJECT = {ROLE_ADMIN, ROLE_PROJECT_MANAGER}
MANAGERS = {ROLE_ADMIN, ROLE_CRM_MANAGER, ROLE_PROJECT_MANAGER}
WORK = {ROLE_ADMIN, ROLE_PROJECT_MANAGER, ROLE_EMPLOYEE}
ATTENDANCE = {ROLE_ADMIN, ROLE_PROJECT_MANAGER, ROLE_EMPLOYEE}


def _item(label, url_name, icon, roles=None, match=(), exclude=()):
    return {
        "label": label,
        "url_name": url_name,
        "icon": icon,
        "roles": roles,
        "match": match,
        "exclude": exclude,
    }


NAVIGATION = [
    {
        "title": "Overview",
        "items": [
            _item("Dashboard", "ui:home", "bi-grid-1x2"),
            _item("To Do", "todos:todo_list", "bi-check2-square", match=("/todos/",)),
        ],
    },
    {
        "title": "Sales pipeline",
        "items": [
            _item("Inquiries", "crm:inquiry_list", "bi-inbox", match=("/crm/inquiries/",)),
            _item("Leads", "crm:lead_list", "bi-person-lines-fill", SALES, match=("/crm/leads/",)),
            _item("Deals", "sales:deal_list", "bi-briefcase", SALES, match=("/sales/deals/",)),
            _item("Proposals", "sales:proposal_list", "bi-file-earmark-richtext", SALES, match=("/sales/proposals/",)),
            # Production staff open a contract from its event, not from the sales list.
            _item("Contracts", "sales:contract_list", "bi-file-earmark-check", SALES, match=("/sales/contracts/",)),
        ],
    },
    {
        "title": "Billing",
        "items": [
            _item("Invoices", "sales:invoice_list", "bi-receipt", SALES, match=("/sales/invoices/",)),
            _item("Payments", "sales:payment_list", "bi-cash-coin", SALES, match=("/sales/payments/",)),
        ],
    },
    {
        "title": "Clients & events",
        "items": [
            _item(
                "Clients",
                "crm:client_list",
                "bi-people",
                SALES,
                match=("/crm/clients/", "/crm/contacts/", "/crm/reviews/"),
            ),
            _item(
                "Events",
                "events:event_list",
                "bi-stars",
                MANAGERS,
                match=("/events/events/",),
            ),
            _item("Venues", "events:venue_list", "bi-geo-alt", MANAGERS, match=("/events/venues/",)),
            _item(
                "Checklists",
                "events:checklist_list",
                "bi-list-check",
                MANAGERS,
                match=("/events/checklists/", "/events/checklist-items/"),
            ),
        ],
    },
    {
        "title": "Production",
        "items": [
            _item(
                "Projects",
                "projects:project_kanban",
                "bi-kanban",
                PROJECT,
                match=("/projects/projects/",),
            ),
            _item("Tasks", "projects:task_kanban", "bi-list-task", WORK, match=("/projects/tasks/",)),
            _item(
                "Deliverables",
                "projects:deliverable_kanban",
                "bi-box-seam",
                WORK,
                match=("/projects/deliverables/",),
            ),
        ],
    },
    {
        "title": "Calendars",
        "items": [
            _item("Event calendar", "events:event_calendar", "bi-calendar-event"),
            _item("Work calendar", "projects:project_calendar", "bi-calendar-week", WORK),
        ],
    },
    {
        "title": "Catalog",
        "items": [
            _item("Services", "services:service_list", "bi-camera", ADMIN, match=("/services/services/",)),
            _item("Packages", "services:package_list", "bi-boxes", ADMIN, match=("/services/packages/",)),
            _item("Vendors", "services:vendor_list", "bi-shop", ADMIN, match=("/services/vendors/",)),
            _item("Inventory", "services:inventory_list", "bi-hdd-stack", ADMIN, match=("/services/inventory/",)),
        ],
    },
    {
        "title": "Messaging",
        "items": [
            _item("Email templates", "messaging:template_list", "bi-envelope", SALES, match=("/messaging/templates/",)),
            _item("Email campaigns", "messaging:campaign_list", "bi-megaphone", SALES, match=("/messaging/campaigns/",)),
            _item(
                "WhatsApp templates",
                "messaging:whatsapp_template_list",
                "bi-whatsapp",
                SALES,
                match=("/messaging/whatsapp/templates/",),
            ),
            _item("Email logs", "messaging:email_log_list", "bi-envelope-check", SALES, exclude=("/messaging/logs/whatsapp",)),
            _item("WhatsApp logs", "messaging:whatsapp_log_list", "bi-journal-text", SALES),
        ],
    },
    {
        "title": "Team",
        "items": [
            _item("Reports", "reports:dashboard", "bi-bar-chart-line", MANAGERS, exclude=("/reports/attendance/",)),
            _item("Attendance & leave", "reports:attendance", "bi-clock-history", ATTENDANCE),
            _item("Support tickets", "messaging:ticket_list", "bi-life-preserver", match=("/messaging/tickets/",)),
        ],
    },
    {
        "title": "Administration",
        "items": [
            _item("Users", "adminpanel:user_list", "bi-person-gear", ADMIN, match=("/adminpanel/users/",)),
            _item("Roles & permissions", "adminpanel:role_list", "bi-shield-lock", ADMIN, match=("/adminpanel/roles/",)),
            _item("System settings", "adminpanel:system_settings", "bi-sliders", ADMIN),
        ],
    },
]


def _user_roles(user):
    if user.is_superuser:
        return None  # sees everything
    return set(user.groups.values_list("name", flat=True))


def _is_active(path, url, item):
    if any(path.startswith(prefix) for prefix in item["exclude"]):
        return False
    if path == url:
        return True
    if url != "/" and path.startswith(url):
        return True
    return any(path.startswith(prefix) for prefix in item["match"])


def build_navigation(request):
    user = request.user
    if not user.is_authenticated:
        return []

    roles = _user_roles(user)
    path = request.path
    sections = []

    for group in NAVIGATION:
        items = []
        for item in group["items"]:
            if item["roles"] is not None and roles is not None and not (item["roles"] & roles):
                continue
            try:
                url = reverse(item["url_name"])
            except NoReverseMatch:
                continue
            items.append({
                "label": item["label"],
                "url": url,
                "icon": item["icon"],
                "active": _is_active(path, url, item),
            })
        if items:
            sections.append({
                "title": group["title"],
                "items": items,
                "active": any(i["active"] for i in items),
            })

    return sections
