from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import permission_classes
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Count
from apps.transactions.models import SaleInvoice, PurchaseInvoice
from apps.catalog.models import Item

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_data_api(request):
    company = request.user.profile.company
    today = timezone.now().date()
    
    # Basic Stats
    total_items = Item.objects.filter(company=company).count()
    total_sales_today = SaleInvoice.objects.filter(company=company, date_dispatched=today).aggregate(total=Sum('grand_total'))['total'] or 0
    
    # Dummy data structure to match frontend expectations
    data = {
        "success": True,
        "greeting": "Good morning",
        "stat_cards": [
            {"label": "Total Items", "value": total_items, "badge": "Active", "badge_type": "green"},
            {"label": "Sales Today", "value": f"Rs. {total_sales_today}", "badge": "Today", "badge_type": "blue"},
        ],
        "charts": {
            "trend": {
                "labels": [str(today - timedelta(days=i)) for i in range(30, 0, -1)],
                "sales": [0]*30,
                "purchases": [0]*30,
                "spoilage": [0]*30
            },
            "payment_status": {
                "labels": ["Paid", "Partial", "Unpaid"],
                "data": [0, 0, 0]
            }
        },
        "activity": [],
        "low_stock_alerts": []
    }
    return Response(data)