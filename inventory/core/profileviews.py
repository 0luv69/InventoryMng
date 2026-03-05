
import json
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth import authenticate, login
from .models import UserProfile, Company, UserSession
from django.utils import timezone
from django.conf import settings
from .utils import get_client_ip, short_user_agent


def profile_view(request):
    if not request.user.is_authenticated:
        return redirect("login")

    userProfile = get_object_or_404(UserProfile, user=request.user)

    print("User Profile:", userProfile)
    userSession = UserSession.objects.filter(user=request.user).order_by("-last_activity")[:20]

    context = {
        "title": "Profile",
        "userProfile": userProfile,
        "PRODUCTION_URL": settings.PRODUCTION_URL,
        "userSessions": userSession,
    }
    return render(request, "core/profile.html", context)



def update_profile(request):
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
    UserSession.objects.filter(user=request.user).update(is_active=False)  # Invalidate all existing sessions for the user

    s_user_agent = short_user_agent(request.META.get("HTTP_USER_AGENT", ""))
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    UserSession.objects.create(
        user=request.user,
        uuid = uuid.uuid4(),
        session_key=session_key,
        ip_address=get_client_ip(request),
        user_agent=s_user_agent,
    )
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

