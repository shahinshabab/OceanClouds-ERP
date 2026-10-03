# reports/urls.py

from django.urls import path

from .views import (
    ReportDashboardView,
    SalesReportView,
    ProjectReportView,
    EmployeeWorkReportView,
    AttendanceDashboardView,
)

app_name = "reports"

urlpatterns = [
    path("", ReportDashboardView.as_view(), name="dashboard"),
    path("sales/", SalesReportView.as_view(), name="sales_report"),
    path("projects/", ProjectReportView.as_view(), name="project_report"),
    path("employees/", EmployeeWorkReportView.as_view(), name="employee_work_report"),
    path("attendance/", AttendanceDashboardView.as_view(), name="attendance"),
]
