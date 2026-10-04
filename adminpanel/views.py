from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView

from common.roles import ROLE_ADMIN, user_has_role

from .models import SystemSetting

from .forms import (
    UserCreateForm,
    UserUpdateForm,
    RoleForm,
    SystemSettingForm,
)


User = get_user_model()


class AdminPanelRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Only Admins (and superusers) may manage users, roles and settings.

    Being `is_staff` alone is not enough: these pages can grant any role or
    permission, so a staff flag would otherwise be a path to full control.
    """

    def test_func(self):
        return user_has_role(self.request.user, ROLE_ADMIN)

    def handle_no_permission(self):
        messages.error(
            self.request,
            "You do not have permission to access the admin panel.",
        )
        return super().handle_no_permission()


# ---------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------

class UserListView(AdminPanelRequiredMixin, ListView):
    model = User
    template_name = "adminpanel/user_list.html"
    context_object_name = "users"
    paginate_by = 25

    def get_queryset(self):
        qs = User.objects.prefetch_related("groups").order_by("username")

        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        role = self.request.GET.get("role", "").strip()

        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
            )

        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)

        if role:
            qs = qs.filter(groups__id=role)

        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        context["status"] = self.request.GET.get("status", "")
        context["selected_role"] = self.request.GET.get("role", "")
        context["roles"] = Group.objects.all().order_by("name")
        return context


class SuperuserFieldMixin:
    """Only a superuser can create or change superusers."""

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not self.request.user.is_superuser:
            form.fields.pop("is_superuser", None)
        return form


class UserCreateView(AdminPanelRequiredMixin, SuperuserFieldMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = "adminpanel/user_form.html"
    success_url = reverse_lazy("adminpanel:user_list")

    def form_valid(self, form):
        messages.success(self.request, "User created successfully.")
        return super().form_valid(form)


class UserUpdateView(AdminPanelRequiredMixin, SuperuserFieldMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = "adminpanel/user_form.html"
    success_url = reverse_lazy("adminpanel:user_list")

    def form_valid(self, form):
        messages.success(self.request, "User updated successfully.")
        return super().form_valid(form)


# ---------------------------------------------------------------------
# Roles / Groups
# ---------------------------------------------------------------------

class RoleListView(AdminPanelRequiredMixin, ListView):
    model = Group
    template_name = "adminpanel/role_list.html"
    context_object_name = "roles"
    paginate_by = 25

    def get_queryset(self):
        qs = Group.objects.prefetch_related("permissions").order_by("name")

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        return context


class RoleCreateView(AdminPanelRequiredMixin, CreateView):
    model = Group
    form_class = RoleForm
    template_name = "adminpanel/role_form.html"
    success_url = reverse_lazy("adminpanel:role_list")

    def form_valid(self, form):
        messages.success(self.request, "Role created successfully.")
        return super().form_valid(form)


class RoleUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = Group
    form_class = RoleForm
    template_name = "adminpanel/role_form.html"
    success_url = reverse_lazy("adminpanel:role_list")

    def form_valid(self, form):
        messages.success(self.request, "Role updated successfully.")
        return super().form_valid(form)


# ---------------------------------------------------------------------
# System Settings
# ---------------------------------------------------------------------

class SystemSettingUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = SystemSetting
    form_class = SystemSettingForm
    template_name = "adminpanel/system_settings_form.html"
    success_url = reverse_lazy("adminpanel:system_settings")

    def get_object(self, queryset=None):
        obj, _ = SystemSetting.objects.get_or_create(pk=1)
        return obj

    def form_valid(self, form):
        messages.success(self.request, "System settings updated successfully.")
        return super().form_valid(form)