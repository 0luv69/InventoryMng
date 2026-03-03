from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models import Sum, F, Q
from datetime import timedelta


# ──────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────

def home(request):
  context = {
    "title": "Home",
  }
  return render(request, "home.html", context)


def home2(request):
  context = {
    "title": "Home",
  }
  return render(request, "base2.html", context)