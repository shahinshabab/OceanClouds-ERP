# services/views.py

from django.contrib import messages
from django.db.models import Q
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)
from django.shortcuts import redirect

from common.mixins import AdminOnlyMixin

from .models import (
    Vendor,
    Service,
    Package,
    InventoryItem,
    ServiceCategory,
    VendorType,
    InventoryCategory,
)

from .forms import (
    VendorForm,
    ServiceForm,
    ServiceDeliverableFormSet,
    PackageForm,
    PackageItemFormSet,
    PackageDeliverableFormSet,
    InventoryItemForm,
)



# -------------------------------------------------------------------
# Common Services Delete Mixin
# -------------------------------------------------------------------

class ServicesCommonDeleteMixin(AdminOnlyMixin, DeleteView):
    """
    Common delete view for Services app master data.

    Access:
    - Admin only

    Uses:
    - ui/templates/common/confirm_delete.html
    """

    template_name = "services/confirm_delete.html"
    object_type = "item"
    success_message = "Item deleted successfully."
    warning_message = ""
    cancel_url_name = None

    def get_object_label(self):
        return str(self.object)

    def get_cancel_url(self):
        if self.cancel_url_name:
            return reverse(self.cancel_url_name)
        return self.get_success_url()

    def get_related_counts(self):
        """
        Override in child classes if needed.
        Must return list of tuples:
        [
            ("Related Services", 3),
            ("Inventory Items", 2),
        ]
        """
        return []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["object_type"] = self.object_type
        context["object_label"] = self.get_object_label()
        context["warning_message"] = self.warning_message
        context["related_counts"] = self.get_related_counts()
        context["cancel_url"] = self.get_cancel_url()

        return context

    def form_valid(self, form):
        messages.success(self.request, self.success_message)
        return super().form_valid(form)
    
# -------------------------------------------------------------------
# Vendor Views
# -------------------------------------------------------------------

class VendorListView(AdminOnlyMixin, ListView):
    model = Vendor
    template_name = "services/vendor_list.html"
    context_object_name = "vendors"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()

        q = self.request.GET.get("q", "").strip()
        vendor_type = self.request.GET.get("vendor_type", "").strip()
        preferred = self.request.GET.get("preferred", "").strip()
        is_active = self.request.GET.get("is_active", "").strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(company_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(whatsapp__icontains=q)
                | Q(email__icontains=q)
            )

        if vendor_type:
            qs = qs.filter(vendor_type=vendor_type)

        if preferred == "yes":
            qs = qs.filter(is_preferred=True)
        elif preferred == "no":
            qs = qs.filter(is_preferred=False)

        if is_active == "active":
            qs = qs.filter(is_active=True)
        elif is_active == "inactive":
            qs = qs.filter(is_active=False)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "").strip()
        context["vendor_type"] = self.request.GET.get("vendor_type", "").strip()
        context["preferred"] = self.request.GET.get("preferred", "").strip()
        context["is_active"] = self.request.GET.get("is_active", "").strip()
        context["vendor_type_choices"] = VendorType.choices
        return context


class VendorDetailView(AdminOnlyMixin, DetailView):
    model = Vendor
    template_name = "services/vendor_detail.html"
    context_object_name = "vendor"


class VendorCreateView(AdminOnlyMixin, CreateView):
    model = Vendor
    form_class = VendorForm
    template_name = "services/vendor_form.html"
    success_url = reverse_lazy("services:vendor_list")

    def form_valid(self, form):
        form.instance.owner = self.request.user
        messages.success(self.request, "Vendor created successfully.")
        return super().form_valid(form)


class VendorUpdateView(AdminOnlyMixin, UpdateView):
    model = Vendor
    form_class = VendorForm
    template_name = "services/vendor_form.html"
    success_url = reverse_lazy("services:vendor_list")

    def form_valid(self, form):
        messages.success(self.request, "Vendor updated successfully.")
        return super().form_valid(form)


class VendorDeleteView(ServicesCommonDeleteMixin):
    model = Vendor
    success_url = reverse_lazy("services:vendor_list")
    cancel_url_name = "services:vendor_list"

    object_type = "vendor"
    success_message = "Vendor deleted successfully."
    warning_message = (
        "This vendor may be linked to services. Deleting the vendor will remove "
        "the vendor record and unlink it from related services."
    )

    def get_related_counts(self):
        return [
            ("Linked Services", self.object.services.count()),
        ]


# -------------------------------------------------------------------
# Service Views
# -------------------------------------------------------------------

class ServiceListView(AdminOnlyMixin, ListView):
    model = Service
    template_name = "services/service_list.html"
    context_object_name = "services"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related("vendors")

        q = self.request.GET.get("q", "").strip()
        category = self.request.GET.get("category", "").strip()
        is_active = self.request.GET.get("is_active", "").strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(code__icontains=q)
                | Q(description__icontains=q)
            )

        if category:
            qs = qs.filter(category=category)

        if is_active == "active":
            qs = qs.filter(is_active=True)
        elif is_active == "inactive":
            qs = qs.filter(is_active=False)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "").strip()
        context["category"] = self.request.GET.get("category", "").strip()
        context["is_active"] = self.request.GET.get("is_active", "").strip()
        context["category_choices"] = ServiceCategory.choices
        return context


class ServiceDetailView(AdminOnlyMixin, DetailView):
    model = Service
    template_name = "services/service_detail.html"
    context_object_name = "service"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("vendors", "deliverables", "inventory_items")


class ServiceCreateView(AdminOnlyMixin, CreateView):
    model = Service
    form_class = ServiceForm
    template_name = "services/service_form.html"
    success_url = reverse_lazy("services:service_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.POST:
            context["deliverables_formset"] = ServiceDeliverableFormSet(
                self.request.POST,
                prefix="deliverables",
            )
        else:
            context["deliverables_formset"] = ServiceDeliverableFormSet(prefix="deliverables")

        return context

    def form_valid(self, form):
        context = self.get_context_data(form=form)
        deliverables_formset = context["deliverables_formset"]

        if not deliverables_formset.is_valid():
            return self.render_to_response(context)

        form.instance.owner = self.request.user
        self.object = form.save()
        deliverables_formset.instance = self.object
        deliverables_formset.save()
        messages.success(self.request, "Service created successfully.")
        return redirect(self.get_success_url())


class ServiceUpdateView(AdminOnlyMixin, UpdateView):
    model = Service
    form_class = ServiceForm
    template_name = "services/service_form.html"
    success_url = reverse_lazy("services:service_list")

    def get_queryset(self):
        return super().get_queryset().prefetch_related("deliverables")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.POST:
            context["deliverables_formset"] = ServiceDeliverableFormSet(
                self.request.POST,
                instance=self.object,
                prefix="deliverables",
            )
        else:
            context["deliverables_formset"] = ServiceDeliverableFormSet(
                instance=self.object,
                prefix="deliverables",
            )

        return context

    def form_valid(self, form):
        context = self.get_context_data(form=form)
        deliverables_formset = context["deliverables_formset"]

        if not deliverables_formset.is_valid():
            return self.render_to_response(context)

        self.object = form.save()
        deliverables_formset.instance = self.object
        deliverables_formset.save()
        messages.success(self.request, "Service updated successfully.")
        return redirect(self.get_success_url())


class ServiceDeleteView(ServicesCommonDeleteMixin):
    model = Service
    success_url = reverse_lazy("services:service_list")
    cancel_url_name = "services:service_list"

    object_type = "service"
    success_message = "Service deleted successfully."
    warning_message = (
        "This service may be linked to packages and inventory items. "
        "Package items and inventory links may be affected depending on your model relationships."
    )

    def get_related_counts(self):
        return [
            ("Package Items", self.object.package_items.count()),
            ("Inventory Items", self.object.inventory_items.count()),
            ("Linked Vendors", self.object.vendors.count()),
        ]


# -------------------------------------------------------------------
# Package Views
# -------------------------------------------------------------------

class PackageListView(AdminOnlyMixin, ListView):
    model = Package
    template_name = "services/package_list.html"
    context_object_name = "packages"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()

        q = self.request.GET.get("q", "").strip()
        is_active = self.request.GET.get("is_active", "").strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(code__icontains=q)
                | Q(description__icontains=q)
            )

        if is_active == "active":
            qs = qs.filter(is_active=True)
        elif is_active == "inactive":
            qs = qs.filter(is_active=False)
        price_order = self.request.GET.get("price_order", "").strip()

        if price_order == "low_high":
            qs = qs.order_by("total_price", "name")
        elif price_order == "high_low":
            qs = qs.order_by("-total_price", "name")
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "").strip()
        context["is_active"] = self.request.GET.get("is_active", "").strip()
        context["price_order"] = self.request.GET.get("price_order", "").strip()
        return context


class PackageDetailView(AdminOnlyMixin, DetailView):
    model = Package
    template_name = "services/package_detail.html"
    context_object_name = "package"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("items", "items__service", "deliverables")


class PackageCreateView(AdminOnlyMixin, CreateView):
    model = Package
    form_class = PackageForm
    template_name = "services/package_form.html"
    success_url = reverse_lazy("services:package_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.POST:
            context["items_formset"] = PackageItemFormSet(
                self.request.POST,
                prefix="items",
            )
            context["deliverables_formset"] = PackageDeliverableFormSet(
                self.request.POST,
                prefix="deliverables",
            )
        else:
            context["items_formset"] = PackageItemFormSet(prefix="items")
            context["deliverables_formset"] = PackageDeliverableFormSet(prefix="deliverables")

        return context

    def form_valid(self, form):
        context = self.get_context_data()
        items_formset = context["items_formset"]
        deliverables_formset = context["deliverables_formset"]

        form.instance.owner = self.request.user

        if items_formset.is_valid() and deliverables_formset.is_valid():
            self.object = form.save()
            items_formset.instance = self.object
            items_formset.save()
            deliverables_formset.instance = self.object
            deliverables_formset.save()
            self.object.recalculate_total()

            messages.success(self.request, "Package created successfully.")
            return redirect(self.get_success_url())

        return self.render_to_response(self.get_context_data(form=form))


class PackageUpdateView(AdminOnlyMixin, UpdateView):
    model = Package
    form_class = PackageForm
    template_name = "services/package_form.html"
    success_url = reverse_lazy("services:package_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.POST:
            context["items_formset"] = PackageItemFormSet(
                self.request.POST,
                instance=self.object,
                prefix="items",
            )
            context["deliverables_formset"] = PackageDeliverableFormSet(
                self.request.POST,
                instance=self.object,
                prefix="deliverables",
            )
        else:
            context["items_formset"] = PackageItemFormSet(
                instance=self.object,
                prefix="items",
            )
            context["deliverables_formset"] = PackageDeliverableFormSet(
                instance=self.object,
                prefix="deliverables",
            )

        return context

    def form_valid(self, form):
        context = self.get_context_data()
        items_formset = context["items_formset"]
        deliverables_formset = context["deliverables_formset"]

        if items_formset.is_valid() and deliverables_formset.is_valid():
            self.object = form.save()
            items_formset.instance = self.object
            items_formset.save()
            deliverables_formset.instance = self.object
            deliverables_formset.save()
            self.object.recalculate_total()

            messages.success(self.request, "Package updated successfully.")
            return redirect(self.get_success_url())

        return self.render_to_response(self.get_context_data(form=form))


class PackageDeleteView(ServicesCommonDeleteMixin):
    model = Package
    success_url = reverse_lazy("services:package_list")
    cancel_url_name = "services:package_list"

    object_type = "package"
    success_message = "Package deleted successfully."
    warning_message = (
        "Deleting this package will also delete all package item rows inside it."
    )

    def get_related_counts(self):
        return [
            ("Package Items", self.object.items.count()),
        ]

# -------------------------------------------------------------------
# Inventory Views
# -------------------------------------------------------------------

class InventoryItemListView(AdminOnlyMixin, ListView):
    model = InventoryItem
    template_name = "services/inventory_list.html"
    context_object_name = "inventory_items"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("service")

        q = self.request.GET.get("q", "").strip()
        category = self.request.GET.get("category", "").strip()
        service_id = self.request.GET.get("service", "").strip()
        stock_status = self.request.GET.get("stock_status", "").strip()
        is_active = self.request.GET.get("is_active", "").strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(sku__icontains=q)
                | Q(location__icontains=q)
            )

        if category:
            qs = qs.filter(category=category)

        if service_id:
            qs = qs.filter(service_id=service_id)

        if stock_status == "in_stock":
            qs = qs.filter(quantity_available__gt=0)
        elif stock_status == "out_of_stock":
            qs = qs.filter(quantity_available__lte=0)

        if is_active == "active":
            qs = qs.filter(is_active=True)
        elif is_active == "inactive":
            qs = qs.filter(is_active=False)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "").strip()
        context["category"] = self.request.GET.get("category", "").strip()
        context["service_filter"] = self.request.GET.get("service", "").strip()
        context["stock_status"] = self.request.GET.get("stock_status", "").strip()
        context["is_active"] = self.request.GET.get("is_active", "").strip()
        context["category_choices"] = InventoryCategory.choices
        context["service_choices"] = Service.objects.filter(is_active=True).order_by("name")
        return context


class InventoryItemDetailView(AdminOnlyMixin, DetailView):
    model = InventoryItem
    template_name = "services/inventory_detail.html"
    context_object_name = "inventory_item"


class InventoryItemCreateView(AdminOnlyMixin, CreateView):
    model = InventoryItem
    form_class = InventoryItemForm
    template_name = "services/inventory_form.html"
    success_url = reverse_lazy("services:inventory_list")

    def form_valid(self, form):
        form.instance.owner = self.request.user
        messages.success(self.request, "Inventory item created successfully.")
        return super().form_valid(form)


class InventoryItemUpdateView(AdminOnlyMixin, UpdateView):
    model = InventoryItem
    form_class = InventoryItemForm
    template_name = "services/inventory_form.html"
    success_url = reverse_lazy("services:inventory_list")

    def form_valid(self, form):
        messages.success(self.request, "Inventory item updated successfully.")
        return super().form_valid(form)


class InventoryItemDeleteView(ServicesCommonDeleteMixin):
    model = InventoryItem
    success_url = reverse_lazy("services:inventory_list")
    cancel_url_name = "services:inventory_list"

    object_type = "inventory item"
    success_message = "Inventory item deleted successfully."
    warning_message = (
        "This will delete the inventory item from your company asset list."
    )

    def get_related_counts(self):
        related = []

        if self.object.service:
            related.append(("Linked Service", self.object.service.name))
        else:
            related.append(("Linked Service", "—"))

        related.append(("Available Quantity", self.object.quantity_available))
        related.append(("Total Quantity", self.object.quantity_total))

        return related
