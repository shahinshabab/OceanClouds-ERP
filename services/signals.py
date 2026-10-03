# services/signals.py

from decimal import Decimal

from django.apps import apps
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from services.models import (
    Service,
    ServiceCategory,
    ServiceDeliverable,
    Package,
    PackageItem,
    PackageDeliverable,
    DeliverableUnit,
)


@receiver(post_migrate)
def create_basic_wedding_services(sender, **kwargs):
    """
    Initializes basic wedding services/packages after migration.

    This runs only for the services app.
    It is safe because get_or_create avoids duplicates.
    """

    if sender.name != "services":
        return

    service_data = [
        {
            "name": "Wedding Photography",
            "category": ServiceCategory.PHOTOGRAPHY,
            "base_price": Decimal("25000.00"),
            "description": "Professional photography coverage for wedding events.",
            "deliverables": [
                ("Event photography coverage", "Professional photographer coverage for the event.", Decimal("1.00"), DeliverableUnit.ITEM),
                ("Edited photos", "Final colour-corrected and edited photographs.", Decimal("250.00"), DeliverableUnit.PHOTO),
                ("Online gallery", "Online gallery for viewing and sharing selected photos.", Decimal("1.00"), DeliverableUnit.ITEM),
            ],
        },
        {
            "name": "Wedding Videography",
            "category": ServiceCategory.VIDEOGRAPHY,
            "base_price": Decimal("35000.00"),
            "description": "Professional wedding video coverage.",
            "deliverables": [
                ("Event videography coverage", "Professional videographer coverage for the event.", Decimal("1.00"), DeliverableUnit.ITEM),
                ("Edited full video", "Final edited full event video.", Decimal("1.00"), DeliverableUnit.VIDEO),
                ("Highlight video", "Short cinematic highlight video.", Decimal("1.00"), DeliverableUnit.VIDEO),
            ],
        },
        {
            "name": "Drone Coverage",
            "category": ServiceCategory.DRONE,
            "base_price": Decimal("15000.00"),
            "description": "Drone video/photo coverage for outdoor wedding visuals.",
            "deliverables": [
                ("Drone shoot", "Aerial photo/video coverage subject to location and permission.", Decimal("1.00"), DeliverableUnit.ITEM),
                ("Drone video clips", "Edited drone clips included in final video.", Decimal("1.00"), DeliverableUnit.VIDEO),
            ],
        },
        {
            "name": "Premium Wedding Album",
            "category": ServiceCategory.ALBUM,
            "base_price": Decimal("18000.00"),
            "description": "Premium printed wedding album.",
            "deliverables": [
                ("Premium album", "Printed premium wedding album.", Decimal("1.00"), DeliverableUnit.ALBUM),
                ("Album design", "Custom album layout and design.", Decimal("1.00"), DeliverableUnit.ITEM),
            ],
        },
    ]

    created_services = {}

    for service_index, item in enumerate(service_data):
        service, _ = Service.objects.get_or_create(
            name=item["name"],
            defaults={
                "category": item["category"],
                "base_price": item["base_price"],
                "description": item["description"],
                "is_active": True,
            },
        )

        created_services[item["name"]] = service

        for deliverable_index, deliverable in enumerate(item["deliverables"]):
            title, description, quantity, unit = deliverable

            ServiceDeliverable.objects.get_or_create(
                service=service,
                title=title,
                defaults={
                    "description": description,
                    "quantity": quantity,
                    "unit": unit,
                    "sort_order": deliverable_index,
                    "is_active": True,
                },
            )

    package, _ = Package.objects.get_or_create(
        name="Standard Wedding Coverage Package",
        defaults={
            "description": "Standard wedding package including photography and videography.",
            "is_active": True,
        },
    )

    package_items = [
        ("Wedding Photography - Standard Coverage", "Wedding Photography", 1),
        ("Wedding Videography - Standard Coverage", "Wedding Videography", 1),
    ]

    for index, (description, service_name, quantity) in enumerate(package_items):
        service = created_services.get(service_name)

        if not service:
            continue

        PackageItem.objects.get_or_create(
            package=package,
            service=service,
            description=description,
            defaults={
                "quantity": quantity,
                "unit_price": service.base_price,
                "sort_order": index,
            },
        )

    package_deliverables = [
        (
            "Complete wedding event coverage",
            "Photography and videography coverage as per selected event schedule.",
            Decimal("1.00"),
            DeliverableUnit.ITEM,
        ),
        (
            "Edited media delivery",
            "Final edited photos and videos will be delivered after post-production.",
            Decimal("1.00"),
            DeliverableUnit.ITEM,
        ),
        (
            "Online sharing support",
            "Selected digital files can be shared through online gallery or drive link.",
            Decimal("1.00"),
            DeliverableUnit.ITEM,
        ),
    ]

    for index, deliverable in enumerate(package_deliverables):
        title, description, quantity, unit = deliverable

        PackageDeliverable.objects.get_or_create(
            package=package,
            title=title,
            defaults={
                "description": description,
                "quantity": quantity,
                "unit": unit,
                "sort_order": index,
                "is_active": True,
            },
        )

    package.recalculate_total(save=True)