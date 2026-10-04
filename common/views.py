from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import ImportantNotice, Notification, UserLoginSession, UserNoticeAcknowledgement
from .browser_presence import heartbeat_interval
from .session_management import close_expired_login_sessions, idle_cutoff
from .signals import get_client_ip


def _session_ended(request):
    """401 telling the page why its login ended, so it can say so on sign-in."""
    session_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
    reason = ""
    if session_key:
        reason = (
            UserLoginSession.objects.filter(session_key=session_key)
            .exclude(logout_at__isnull=True)
            .order_by("-login_at")
            .values_list("end_reason", flat=True)
            .first()
        ) or ""
    return JsonResponse({"error": "Session ended", "reason": reason}, status=401)


@never_cache
@require_POST
def session_heartbeat(request):
    """
    Pages send this at most once a minute, and only after someone interacted
    with them, so it refreshes this login's last activity time.
    """
    if not request.user.is_authenticated or not request.session.session_key:
        return _session_ended(request)

    now = timezone.now()
    current_login = UserLoginSession.objects.filter(
        user_id=request.user.pk,
        session_key=request.session.session_key,
        logout_at__isnull=True,
    ).filter(Q(expires_at__gt=now) | Q(expires_at__isnull=True))
    cutoff = idle_cutoff(now)
    if cutoff is not None:
        current_login = current_login.filter(last_activity_at__gt=cutoff)
    updated = current_login.filter(
        last_activity_at__lte=now - heartbeat_interval()
    ).update(last_activity_at=now)
    if not updated and not current_login.exists():
        # Idle or past its deadline: end it now rather than at the next cleanup.
        if request.session.session_key in close_expired_login_sessions(now):
            auth_logout(request)
        return _session_ended(request)
    return HttpResponse(status=204)


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


@never_cache
@login_required
def notification_panel(request):
    """Fresh bell badge count and dropdown body for live updates."""
    html = render_to_string("ui/partials/notifications_panel.html", request=request)
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({"count": count, "html": html})


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


class ImportantNoticeView(LoginRequiredMixin, View):
    template_name = "common/important_notice.html"

    def pending_notice(self):
        now = timezone.now()
        return (
            ImportantNotice.objects
            .filter(
                is_active=True,
                requires_acknowledgement=True,
                published_at__lte=now,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .exclude(acknowledgements__user=self.request.user)
            .first()
        )

    def safe_next_url(self):
        next_url = self.request.POST.get("next") or self.request.GET.get("next") or ""
        if url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("ui:home")

    def get(self, request):
        notice = self.pending_notice()
        if notice is None:
            return redirect(self.safe_next_url())
        return render(
            request,
            self.template_name,
            {"notice": notice, "next": self.safe_next_url()},
        )

    def post(self, request):
        notice = self.pending_notice()
        if notice is not None:
            UserNoticeAcknowledgement.objects.get_or_create(
                notice=notice,
                user=request.user,
                defaults={
                    "ip_address": get_client_ip(request),
                    "user_agent": request.META.get("HTTP_USER_AGENT", ""),
                },
            )

        if self.pending_notice() is not None:
            return redirect(
                f"{reverse('common:important_notice')}?"
                + urlencode({"next": self.safe_next_url()})
            )
        return redirect(self.safe_next_url())
