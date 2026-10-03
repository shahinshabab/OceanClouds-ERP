# common/roles.py

ROLE_ADMIN = "Admin"
ROLE_CRM_MANAGER = "CRM Manager"
ROLE_PROJECT_MANAGER = "Project Manager"
ROLE_EMPLOYEE = "Employee"


CRM_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
]

SALES_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
]

PROJECT_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_PROJECT_MANAGER,
]

PROJECT_WORK_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
]

INQUIRY_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
]

INQUIRY_MANAGE_ROLES = [
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_PROJECT_MANAGER,
]

# New: Services master data access
SERVICE_ADMIN_ROLES = [
    ROLE_ADMIN,
]

ROLE_ALL = [
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
]

# Event app access

EVENT_MANAGE_ROLES = [
    ROLE_ADMIN,
    ROLE_PROJECT_MANAGER,
]

EVENT_CALENDAR_ROLES = [
    ROLE_ADMIN,
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
]

# Reports access

REPORT_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_PROJECT_MANAGER,
]

SALES_REPORT_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
]

PROJECT_REPORT_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_PROJECT_MANAGER,
]

EMPLOYEE_REPORT_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_PROJECT_MANAGER,
]

ATTENDANCE_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
]


def user_has_role(user, *roles):
    """
    Returns True if user is in ANY of the given roles.
    Superusers always pass.
    """
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return user.groups.filter(name__in=roles).exists()


def can_access_crm(user):
    return user_has_role(user, *CRM_ACCESS_ROLES)


def can_access_sales(user):
    return user_has_role(user, *SALES_ACCESS_ROLES)


def can_access_project(user):
    return user_has_role(user, *PROJECT_ACCESS_ROLES)


def can_access_project_work(user):
    return user_has_role(user, *PROJECT_WORK_ACCESS_ROLES)


def can_access_inquiry(user):
    return user_has_role(user, *INQUIRY_ACCESS_ROLES)


def can_manage_inquiry(user):
    return user_has_role(user, *INQUIRY_MANAGE_ROLES)


def can_manage_services(user):
    """
    Services master data:
    Admin only.
    """
    return user_has_role(user, *SERVICE_ADMIN_ROLES)



def can_manage_events(user):
    """
    Event management:
    Admin + Project Manager.
    """
    return user_has_role(user, *EVENT_MANAGE_ROLES)


def can_access_event_calendar(user):
    """
    Event calendar:
    Admin + Project Manager + Employee.
    """
    return user_has_role(user, *EVENT_CALENDAR_ROLES)


def can_access_reports(user):
    return user_has_role(user, *REPORT_ACCESS_ROLES)


def can_access_sales_report(user):
    return user_has_role(user, *SALES_REPORT_ACCESS_ROLES)


def can_access_project_report(user):
    return user_has_role(user, *PROJECT_REPORT_ACCESS_ROLES)


def can_access_employee_report(user):
    return user_has_role(user, *EMPLOYEE_REPORT_ACCESS_ROLES)


def can_access_attendance(user):
    return user_has_role(user, *ATTENDANCE_ACCESS_ROLES)
