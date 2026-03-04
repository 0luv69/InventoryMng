from django.conf import settings
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



def app_home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    else:
        return redirect("dashboard")

def dashboard(request):
    if not request.user.is_authenticated:
        return redirect("login")
    context = {
        "title": "Dashboard",
    }
    return render(request, "core/dashboard.html", context)



def items_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    context = {
        "title": "Items & Goods",
    }
    return render(request, "core/items-goods.html", context)



def suppliers_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    context = {
        "title": "Suppliers",
    }
    return render(request, "core/suppliers.html", context)


def customers_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    context = {
        "title": "Customers",
    }
    return render(request, "core/customers.html", context)


def goods_in_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    context = {
        "title": "Goods In",
    }
    return render(request, "core/goods-in.html", context)

def goods_out_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    context = {
        "title": "Goods Out",
    }
    return render(request, "core/goods-out.html", context)


def payments_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    context = {
        "title": "Payments",
    }
    return render(request, "core/payment.html", context)


def spoil_damage_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    context = {
        "title": "Spoilage & Loss",
    }
    return render(request, "core/spoil_damage.html", context)


def reports_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    context = {
        "title": "Reports",
    }
    return render(request, "core/reports.html", context)


def profile_view(request):
    if not request.user.is_authenticated:
        return redirect("login")

    userProfile = get_object_or_404(UserProfile, user=request.user)

    print("User Profile:", userProfile)
    context = {
        "title": "Profile",
        "userProfile": userProfile,
        "PRODUCTION_URL": settings.PRODUCTION_URL,
    }
    return render(request, "core/profile.html", context)



def save_profile(request):
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Authentication required."}, status=401)
    
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    
    first_name = (payload.get("first_name") or "").strip()
    last_name = (payload.get("last_name") or "").strip()
    email = (payload.get("email") or "").strip()
    phone = (payload.get("phone") or "").strip()

    if not first_name or not last_name or not email:
        return JsonResponse({"success": False, "message": "First name, last name, and email are required."}, status=400)    
    
    user = request.user
    userProfile = get_object_or_404(UserProfile, user=user)
    user.first_name = first_name
    user.last_name = last_name
    user.email = email
    userProfile.phone_num = phone
    user.save()
    userProfile.save()
    updated_at = timezone.localtime(userProfile.updated_at).strftime("%b %d, %Y %I:%M %p")
    return JsonResponse({"success": True, "message": "Profile updated successfully.", "updated_at": updated_at}, status=200)


def update_pwd(request):
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Authentication required."}, status=401)
    
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    

    try: 
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    
    old_password = payload.get("old_password") or ""
    new_password = payload.get("new_password") or ""
    confirm_pwd = payload.get("confirm_password") or ""

    if not old_password or not new_password:
        return JsonResponse({"success": False, "message": "Old password and new password are required."}, status=400)
    if new_password != confirm_pwd:
        return JsonResponse({"success": False, "message": "New password and confirmation do not match."}, status=400)
    
    if not request.user.check_password(old_password):
        return JsonResponse({"success": False, "message": "Old password is incorrect."}, status=400)

    # Implement password update logic here
    request.user.set_password(new_password)
    request.user.save()
    login(request, request.user)  # Re-authenticate the user after password change

    return JsonResponse({"success": True, "message": "Password updated successfully."}, status=200)



def update_company(request):
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Authentication required."}, status=401)
    
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    email = (payload.get("email") or "").strip()
    address = (payload.get("address") or "").strip()
    city = (payload.get("city") or "").strip()
    state = (payload.get("state") or "").strip()
    country = (payload.get("country") or "").strip()

    currency = (payload.get("currency") or "").strip()
    low_stock_threshold = payload.get("low_stock_threshold")
    tax_id = (payload.get("tax_id") or "").strip()

    if not name:
        return JsonResponse({"success": False, "message": "Company name is required."}, status=400)    
    
    if not email or not city or not country:
        return JsonResponse({"success": False, "message": "Email, city, and country are required."}, status=400)

    if not currency or currency not in dict(Company.CURRENCY_CHOICES):
        return JsonResponse({"success": False, "message": "Valid currency is required."}, status=400)
    
    if low_stock_threshold is not None:
        try:
            low_stock_threshold = int(low_stock_threshold)
            if low_stock_threshold <= 0:
                return JsonResponse({"success": False, "message": "Low stock threshold must be a positive integer."}, status=400)
        except (ValueError, TypeError):
            return JsonResponse({"success": False, "message": "Low stock threshold must be a valid integer."}, status=400)
        
    if tax_id and len(tax_id) > 50:
        return JsonResponse({"success": False, "message": "Tax ID cannot exceed 50 characters."}, status=400)
    
    userProfile = get_object_or_404(UserProfile, user=request.user)
    company = userProfile.company
    company.name = name
    company.phone = phone
    company.email = email
    company.address = address
    company.city = city
    company.state = state
    company.country = country

    if currency in dict(Company.CURRENCY_CHOICES):
        company.currency = currency
    try:
        low_stock_threshold = int(low_stock_threshold)
        if low_stock_threshold > 0:
            company.low_stock_threshold = low_stock_threshold
    except (ValueError, TypeError):
        pass
    company.tax_id = tax_id

    company.save()

    updated_at = timezone.localtime(company.updated_at).strftime("%b %d, %Y %I:%M %p")
    return JsonResponse({"success": True, "message": "Company updated successfully.", "updated_at": updated_at}, status=200)