from django.contrib.sessions.models import Session
from django.utils import timezone
import json
from django.http import JsonResponse
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from .models import RequestDemo, Company, UserProfile, Unit, UserSession



def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def is_session_currently_active(session_key: str) -> bool:
    return Session.objects.filter(
        session_key=session_key,
        expire_date__gt=timezone.now()
    ).exists()

@login_required
def my_active_sessions(request):
    now = timezone.now()

    user_sessions = UserSession.objects.filter(
        user=request.user,
        is_active=True
    ).order_by("-last_activity")

    session_keys = [s.session_key for s in user_sessions]

    valid_keys = set(
        Session.objects.filter(
            session_key__in=session_keys,
            expire_date__gt=now
        ).values_list("session_key", flat=True)
    )

    data = []
    for s in user_sessions:
        active_now = s.session_key in valid_keys
        if s.is_active != active_now:
            s.is_active = active_now
            s.save(update_fields=["is_active", "updated_at"])

        data.append({
            "id": s.id,
            "session_key": s.session_key,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "last_activity": s.last_activity,
            "is_active": active_now,
            "is_current_session": s.session_key == request.session.session_key,
        })

    return JsonResponse({"sessions": data})



# utils/user_agent.py
def short_user_agent(ua: str) -> str:
    if not ua:
        return "Unknown device"

    ua_l = ua.lower()

    # Browser
    if "edg/" in ua_l:
        browser = "Edge"
    elif "chrome/" in ua_l and "edg/" not in ua_l:
        browser = "Chrome"
    elif "firefox/" in ua_l:
        browser = "Firefox"
    elif "safari/" in ua_l and "chrome/" not in ua_l:
        browser = "Safari"
    else:
        browser = "Browser"

    # OS
    if "windows" in ua_l:
        os = "Windows"
    elif "mac os x" in ua_l and "iphone" not in ua_l:
        os = "macOS"
    elif "android" in ua_l:
        os = "Android"
    elif "iphone" in ua_l or "ipad" in ua_l or "ios" in ua_l:
        os = "iOS"
    elif "linux" in ua_l:
        os = "Linux"
    else:
        os = "Unknown OS"

    return f"{browser} on {os}"