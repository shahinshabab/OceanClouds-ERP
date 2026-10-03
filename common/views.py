from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import ListView

from .models import Notification


class NotificationListView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = "common/notification_list.html"
    context_object_name = "notifications"
    paginate_by = 20

    def get_queryset(self):
        qs = Notification.objects.filter(
            recipient=self.request.user,
        ).select_related("actor", "content_type")

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(message__icontains=q)
                | Q(actor__username__icontains=q)
                | Q(actor__first_name__icontains=q)
                | Q(actor__last_name__icontains=q)
            )

        category = self.request.GET.get("category", "all")
        if category != "all":
            qs = qs.filter(notif_type=category)

        status = self.request.GET.get("status", "all")
        if status == "unread":
            qs = qs.filter(is_read=False)
        elif status == "read":
            qs = qs.filter(is_read=True)

        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["q"] = self.request.GET.get("q", "").strip()
        context["category"] = self.request.GET.get("category", "all")
        context["status"] = self.request.GET.get("status", "all")

        context["category_choices"] = [("all", "All notifications")] + list(Notification.Type.choices)

        context["status_choices"] = [
            ("all", "All"),
            ("unread", "Unread only"),
            ("read", "Read only"),
        ]

        return context


@login_required
def mark_notification_read(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    notif = get_object_or_404(
        Notification,
        pk=pk,
        recipient=request.user,
    )

    if not notif.is_read:
        notif.is_read = True
        notif.save(update_fields=["is_read"])

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"success": True})

    next_url = (
        request.POST.get("next")
        or request.META.get("HTTP_REFERER")
        or reverse("common:notification_list")
    )
    return redirect(next_url)
