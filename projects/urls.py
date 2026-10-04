# projects/urls.py

from django.urls import path
from . import views

app_name = "projects"

urlpatterns = [
    # Projects
    path("projects/", views.ProjectListView.as_view(), name="project_list"),
    path("projects/create/", views.ProjectCreateView.as_view(), name="project_create"),
    path("projects/<int:pk>/", views.ProjectDetailView.as_view(), name="project_detail"),
    path("projects/<int:pk>/overview/", views.ProjectOverviewView.as_view(), name="project_overview"),
    path("projects/<int:pk>/edit/", views.ProjectUpdateView.as_view(), name="project_update"),
    path("projects/kanban/", views.ProjectKanbanView.as_view(), name="project_kanban"),
    path("projects/<int:pk>/set-status/", views.ProjectStatusUpdateView.as_view(), name="project_set_status"),
    path("projects/<int:pk>/close/", views.ProjectCloseView.as_view(), name="project_close"),
    # Tasks
    path("tasks/", views.TaskListView.as_view(), name="task_list"),
    path("tasks/create/", views.TaskCreateView.as_view(), name="task_create"),
    path("projects/<int:project_pk>/tasks/create/", views.TaskCreateView.as_view(), name="task_create_for_project"),
    path("tasks/<int:pk>/", views.TaskDetailView.as_view(), name="task_detail"),
    path("tasks/<int:pk>/edit/", views.TaskUpdateView.as_view(), name="task_update"),
    path("tasks/kanban/", views.TaskKanbanView.as_view(), name="task_kanban"),
    path("tasks/<int:pk>/set-status/", views.TaskStatusUpdateView.as_view(), name="task_set_status"),
    path("tasks/<int:pk>/assign-to-me/", views.TaskSelfAssignView.as_view(), name="task_self_assign"),

    # Deliverables
    path("deliverables/", views.DeliverableListView.as_view(), name="deliverable_list"),
    path("deliverables/create/", views.DeliverableCreateView.as_view(), name="deliverable_create"),
    path("projects/<int:project_pk>/deliverables/create/", views.DeliverableCreateView.as_view(), name="deliverable_create_for_project"),
    path("deliverables/<int:pk>/", views.DeliverableDetailView.as_view(), name="deliverable_detail"),
    path("deliverables/<int:pk>/edit/", views.DeliverableUpdateView.as_view(), name="deliverable_update"),
    path("deliverables/kanban/", views.DeliverableKanbanView.as_view(), name="deliverable_kanban"),
    path("deliverables/<int:pk>/set-status/", views.DeliverableStatusUpdateView.as_view(), name="deliverable_set_status"),
    path("deliverables/<int:pk>/assign-to-me/", views.DeliverableSelfAssignView.as_view(), name="deliverable_self_assign"),
    path("calendar/", views.ProjectCalendarView.as_view(), name="project_calendar"),

    # Work sessions
    path("work/start-task/<int:pk>/", views.StartTaskWorkView.as_view(), name="start_task_work"),
    path("work/start-deliverable/<int:pk>/", views.StartDeliverableWorkView.as_view(), name="start_deliverable_work"),
    path("work/<int:pk>/pause/", views.PauseWorkSessionView.as_view(), name="pause_work"),
    path("work/<int:pk>/resume/", views.ResumeWorkSessionView.as_view(), name="resume_work"),
    path("work/<int:pk>/end/", views.EndWorkSessionView.as_view(), name="end_work"),
    path("work/in-progress/", views.WorkInProgressView.as_view(), name="work_in_progress"),

    # AJAX
    path("ajax/load-tasks/", views.ajax_load_tasks, name="ajax_load_tasks"),
]