from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum
from apps.transactions.models import SaleInvoice, PurchaseInvoice
from apps.catalog.models import Item


@login_required
def dashboard_data_api(request):
    # Guard: users without a company profile get a clean 403, not a 500
    profile = getattr(request.user, 'profile', None)
    company = profile.company if profile else None
    if not company:
        return JsonResponse({"success": False, "error": "No company linked to this account."}, status=403)

    today = timezone.now().date()

    total_items = Item.objects.filter(company=company).count()
    total_sales_today = (SaleInvoice.objects
                         .filter(company=company, date_dispatched=today)
                         .aggregate(total=Sum('grand_total'))['total'] or 0)

    # Time-aware greeting (was hardcoded "Good morning")
    hour = timezone.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"

    data = {
        "success": True,
        "greeting": greeting,
        "stat_cards": [
            {"label": "Total Items", "value": total_items, "badge": "Active", "badge_type": "green"},
            {"label": "Sales Today", "value": f"Rs. {total_sales_today}", "badge": "Today", "badge_type": "blue"},
        ],
        "charts": {
            "trend": {
                "labels": [str(today - timedelta(days=i)) for i in range(30, 0, -1)],
                "sales": [0]*30, "purchases": [0]*30, "spoilage": [0]*30,
            },
            "payment_status": {"labels": ["Paid", "Partial", "Unpaid"], "data": [0, 0, 0]},
        },
        "activity": [],
        "low_stock_alerts": [],
    }
    return JsonResponse(data)