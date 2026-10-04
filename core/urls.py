"""Root URL configuration."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),

    # Custom internal admin panel
    path("adminpanel/", include("adminpanel.urls")),


    # Landing + Dashboard + Layout
    path("", include("ui.urls")),

    # CRM (Clients, Contacts, Leads, Inquiries)
    path("crm/", include("crm.urls", namespace="crm")),

    # Sales (Deals, Proposals, Contracts, Invoices)
    path("sales/", include("sales.urls", namespace="sales")),

    # Events (Event pages, venues, checklist, calendar)
    path("events/", include("events.urls", namespace="events")),

    # Services (Packages, service catalog, vendors)
    path("services/", include("services.urls", namespace="services")),

    # Projects (Tasks, deliverables, project management)
    path("projects/", include("projects.urls", namespace="projects")),

    # Common (tickets, communications, notifications)
    path("common/", include("common.urls", namespace="common")),
    path("messaging/", include("messaging.urls", namespace="messaging")),
    path("reports/", include("reports.urls")),
    path("todos/", include("todos.urls")),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
