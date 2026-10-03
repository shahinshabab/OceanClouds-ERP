# common/mixins.py

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
 
from .roles import (
    ROLE_ADMIN,
    ROLE_PROJECT_MANAGER,
    CRM_ACCESS_ROLES,
    SALES_ACCESS_ROLES,
    PROJECT_ACCESS_ROLES,
    PROJECT_WORK_ACCESS_ROLES,
    INQUIRY_ACCESS_ROLES,
    INQUIRY_MANAGE_ROLES,
    SERVICE_ADMIN_ROLES,
    EVENT_MANAGE_ROLES,
    EVENT_CALENDAR_ROLES,
    REPORT_ACCESS_ROLES,
    SALES_REPORT_ACCESS_ROLES,
    PROJECT_REPORT_ACCESS_ROLES,
    EMPLOYEE_REPORT_ACCESS_ROLES,
    ATTENDANCE_ACCESS_ROLES,
    user_has_role,
)

class RolesRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    allowed_roles = []
    raise_exception = True

    def test_func(self):
        return user_has_role(self.request.user, *self.allowed_roles)


class AdminOnlyMixin(RolesRequiredMixin):
    """
    Use for master data / system setup pages.

    Access:
    - Admin only

    Example:
    - Services
    - Packages
    - Inventory
    - Vendors
    """
    allowed_roles = SERVICE_ADMIN_ROLES


class CRMAccessMixin(RolesRequiredMixin):
    """
    CRM pages:
    - Admin
    - CRM Manager
    """
    allowed_roles = CRM_ACCESS_ROLES


class SalesAccessMixin(RolesRequiredMixin):
    """
    Sales pages:
    - Admin
    - CRM Manager
    """
    allowed_roles = SALES_ACCESS_ROLES

class SalesReadOnlyAccessMixin(RolesRequiredMixin):
    """
    Sales read-only detail pages:
    - Admin
    - CRM Manager
    - Project Manager

    Used only when Project Manager needs to view linked sales details
    from Project Overview.

    Do not use this for create, update, delete, send email,
    accept proposal, convert proposal, generate invoice, or payment creation.
    """
    allowed_roles = SALES_ACCESS_ROLES + [ROLE_PROJECT_MANAGER]


class ProjectAdminOnlyMixin(RolesRequiredMixin):
    """
    Project create/edit pages:
    - Admin only

    Project Manager can view projects and update project status,
    but cannot edit due date, manager, client, deal, or project details.
    """
    allowed_roles = [ROLE_ADMIN]

class ProjectAccessMixin(RolesRequiredMixin):
    """
    Project main pages:
    - Admin
    - Project Manager
    """
    allowed_roles = PROJECT_ACCESS_ROLES


class ProjectWorkAccessMixin(RolesRequiredMixin):
    """
    Task/deliverable/work pages:
    - Admin
    - Project Manager
    - Employee
    """
    allowed_roles = PROJECT_WORK_ACCESS_ROLES


class InquiryAccessMixin(RolesRequiredMixin):
    """
    Inquiry pages:
    - Admin
    - CRM Manager
    - Project Manager
    - Employee
    """
    allowed_roles = INQUIRY_ACCESS_ROLES


class InquiryManageMixin(RolesRequiredMixin):
    """
    Inquiry edit/delete/convert:
    - Admin
    - CRM Manager
    - Project Manager
    """
    allowed_roles = INQUIRY_MANAGE_ROLES


class AdminCRMManagerMixin(CRMAccessMixin):
    pass


class StaffAllMixin(InquiryAccessMixin):
    pass


class InquiryManagerMixin(InquiryManageMixin):
    pass

class EventManageMixin(RolesRequiredMixin):
    """
    Event management pages:
    - Admin
    - Project Manager
    """
    allowed_roles = EVENT_MANAGE_ROLES


class EventCalendarAccessMixin(RolesRequiredMixin):
    """
    Event calendar access:
    - Admin
    - Project Manager
    - Employee
    """
    allowed_roles = EVENT_CALENDAR_ROLES


class ReportAccessMixin(RolesRequiredMixin):
    """
    Reports dashboard:
    - Admin
    - CRM Manager
    - Project Manager
    """
    allowed_roles = REPORT_ACCESS_ROLES


class SalesReportAccessMixin(RolesRequiredMixin):
    """
    Sales report:
    - Admin
    - CRM Manager
    """
    allowed_roles = SALES_REPORT_ACCESS_ROLES


class ProjectReportAccessMixin(RolesRequiredMixin):
    """
    Project report:
    - Admin
    - Project Manager
    """
    allowed_roles = PROJECT_REPORT_ACCESS_ROLES


class EmployeeReportAccessMixin(RolesRequiredMixin):
    """
    Employee work report:
    - Admin
    - Project Manager
    """
    allowed_roles = EMPLOYEE_REPORT_ACCESS_ROLES


class AttendanceAccessMixin(RolesRequiredMixin):
    """Attendance and leave: Admin, Project Manager, and Employee."""

    allowed_roles = ATTENDANCE_ACCESS_ROLES
