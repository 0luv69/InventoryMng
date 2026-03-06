"""
Reusable decorators for views that need authenticated user + company.
"""
import functools
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from .models import UserProfile


def company_required(view_func):
    """
    Decorator for page views.
    Redirects to login if not authenticated.
    Returns (request, userProfile) via request.userProfile.
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        request.userProfile = get_object_or_404(UserProfile, user=request.user)
        return view_func(request, *args, **kwargs)
    return wrapper


def api_login_required(view_func):
    """
    Decorator for JSON API views.
    Returns 401 JSON if not authenticated.
    Attaches request.userProfile and request.company.
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"success": False, "message": "Authentication required."}, status=401)
        try:
            request.userProfile = UserProfile.objects.select_related("company").get(user=request.user)
            request.company = request.userProfile.company
        except UserProfile.DoesNotExist:
            return JsonResponse({"success": False, "message": "User profile not found."}, status=404)
        if not request.company:
            return JsonResponse({"success": False, "message": "No company assigned."}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper