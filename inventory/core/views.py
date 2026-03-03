from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models import Sum, F, Q
from datetime import timedelta
import json
from django.http import JsonResponse
from django.contrib.auth import authenticate, login
from .models import RequestDemo, Company, UserProfile, Unit


# ──────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────




def home(request):
  context = {
    "title": "Home",
  }
  return render(request, "home.html", context)


def login_view(request):
  context = {
    "title": "Login",
  }
  return render(request, "log_sign_page.html", context)

def register_view(request):
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
    return JsonResponse({"detail": "Logged in.", "user": {"id": user.id, "email": user.email}, "redirect_url": "/app/dashboard/"})


def register_api(request):
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