from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models import Sum, F, Q
from datetime import timedelta
import json
from django.http import JsonResponse
from django.contrib.auth import authenticate, login
from .models import RequestDemo, Company, UserProfile, Unit, UserSession
from django.contrib.auth import logout
import uuid
# ──────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────

from .utils import get_client_ip, short_user_agent

def temp(request):
    context = {
        "title": "Temp",
    }
    return render(request, "test.html", context)



def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    context = {
        "title": "Home",
    }
    return render(request, "home.html", context)


# Account related views: login, register, logout, profile, update profile, change password, etc.
def login_view(request):
    context = {
        "title": "Login",
    }
    return render(request, "log_sign_page.html", context)

def contactus_view(request):
    context = {
        "title": "Register",
    }
    return render(request, "log_sign_page.html", context)

def login_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)

    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    if not email or not password:
        return JsonResponse({"detail": "Email and password are required."}, status=400)

    user = authenticate(request, username=email, password=password)
    if user is None:
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    login(request, user)
    s_user_agent = short_user_agent(request.META.get("HTTP_USER_AGENT", ""))
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    UserSession.objects.create(
        user=user,
        uuid = uuid.uuid4(),
        session_key=session_key,
        ip_address=get_client_ip(request),
        user_agent=s_user_agent,
    )

    return JsonResponse({"detail": "Logged in.", "user": {"id": user.id, "email": user.email}, "redirect_url": "/app/dashboard/"})

def contactus_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)
    ...
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)

    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()
    phone = (payload.get("phone") or "").strip()
    remarks = (payload.get("remarks") or "").strip()

    if not name or not email or not phone:
        return JsonResponse({"detail": "Name, email, and phone are required."}, status=400)

    RequestDemo.objects.create(
        name=name,
        email=email,
        phone=phone,
        message=remarks,
    )
    return JsonResponse({"detail": "Your request has been submitted successfully."}, status=201)

def logout_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Not logged in."}, status=401)

    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)

    current_key = request.session.session_key
    UserSession.objects.filter(user=request.user, session_key=current_key).delete()
    logout(request)
    return JsonResponse({"success": True, "detail": "Logged out.", "redirect_url": "/"})


# ---- END OF AUTH VIEWS ----


def app_home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    else:
        return redirect("dashboard")

def dashboard(request):
    if not request.user.is_authenticated:
        return redirect("login")
    
    userProfile = get_object_or_404(UserProfile, user=request.user)

    context = {
        "title": "Dashboard",
        "userProfile": userProfile,
    }
    return render(request, "core/dashboard.html", context)


def items_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    
    userProfile = get_object_or_404(UserProfile, user=request.user)
    context = {
        "title": "Items & Goods",
        "userProfile": userProfile,
    }
    return render(request, "core/items-goods.html", context)



def suppliers_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    userProfile = get_object_or_404(UserProfile, user=request.user)
    context = {
        "title": "Suppliers",
        "userProfile": userProfile,
    }
    return render(request, "core/suppliers.html", context)

def customers_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    
    userProfile = get_object_or_404(UserProfile, user=request.user)
    context = {
        "title": "Customers",
        "userProfile": userProfile,
    }
    return render(request, "core/customers.html", context)

def goods_in_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    
    userProfile = get_object_or_404(UserProfile, user=request.user)
    context = {
        "title": "Goods In",
        "userProfile": userProfile,
    }
    return render(request, "core/goods-in.html", context)

def goods_out_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    userProfile = get_object_or_404(UserProfile, user=request.user)
    context = {
        "title": "Goods Out",
        "userProfile": userProfile,
    }
    return render(request, "core/goods-out.html", context)

def payments_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    userProfile = get_object_or_404(UserProfile, user=request.user)
    context = {
        "title": "Payments",
        "userProfile": userProfile,
    }
    return render(request, "core/payment.html", context)

def spoil_damage_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    userProfile = get_object_or_404(UserProfile, user=request.user)
    context = {
        "title": "Spoilage & Loss",
        "userProfile": userProfile,
    }
    return render(request, "core/spoil_damage.html", context)

def reports_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    userProfile = get_object_or_404(UserProfile, user=request.user)
    context = {
        "title": "Reports",
        "userProfile": userProfile,
    }
    return render(request, "core/reports.html", context)


