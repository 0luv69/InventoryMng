"""
Dashboard JSON API view.

Endpoint:
    GET  /api/dashboard/data/   → all dashboard stats, charts, activity, alerts
"""

import json
from datetime import timedelta
from decimal import Decimal
from collections import defaultdict

from django.http import JsonResponse
from django.db.models import Q, Sum, Count, F, Value, CharField
from django.db.models.functions import Concat, TruncDate
from django.utils import timezone

from ..models import (
    Item, Party, PurchaseInvoice, PurchaseItem,
    SaleInvoice, SaleItem, Payment, SpoilageLoss,
    PaymentStatus,
)
from ..decorators import api_login_required


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _currency_symbol(company):
    """Return the currency symbol for display."""
    symbols = {"NPR": "रु", "INR": "₹", "USD": "$"}
    return symbols.get(company.currency, "रु")


def _fmt(val):
    """Decimal → string, default 0."""
    return str(val or Decimal("0.00"))


def _pct_change(current, previous):
    """Return % change string like '+12%' or '-5%'."""
    if not previous or previous == 0:
        return "+100%" if current and current > 0 else "0%"
    change = ((current - previous) / abs(previous)) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


# ═══════════════════════════════════════════════════════════════
#  MAIN DASHBOARD API
# ═══════════════════════════════════════════════════════════════

@api_login_required
def dashboard_data_api(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    user = request.user
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    month_start = today.replace(day=1)
    prev_month_end = month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    currency = _currency_symbol(company)

    # ─── BASE QUERYSETS ───
    items_qs = Item.objects.filter(company=company, is_active=True)
    suppliers_qs = Party.objects.filter(company=company, party_type="supplier", is_removed=False)
    customers_qs = Party.objects.filter(company=company, party_type="customer", is_removed=False)
    purchases_qs = PurchaseInvoice.objects.filter(company=company, is_void=False)
    sales_qs = SaleInvoice.objects.filter(company=company, is_void=False)
    payments_qs = Payment.objects.filter(company=company, is_void=False)
    spoilage_qs = SpoilageLoss.objects.filter(company=company, is_void=False)

    # ═══════════════════════════════════════════════════════════
    #  1) STAT CARDS
    # ═══════════════════════════════════════════════════════════

    # -- Items --
    total_items = items_qs.count()
    items_this_month = items_qs.filter(created_at__date__gte=month_start).count()
    items_prev_month = items_qs.filter(created_at__date__gte=prev_month_start, created_at__date__lt=month_start).count()

    # -- Low stock --
    low_stock_items = []
    for item in items_qs.select_related("unit", "company"):
        threshold = item.low_stock_threshold or company.default_low_stock_threshold
        if item.quantity_in_stock <= threshold:
            low_stock_items.append({
                "id": item.id,
                "name": item.name,
                "quantity_in_stock": str(item.quantity_in_stock),
                "threshold": threshold,
                "unit": item.unit.short_name if item.unit else "",
            })
    low_stock_count = len(low_stock_items)

    # -- Goods In today --
    purchases_today = purchases_qs.filter(date_received=today)
    purchases_today_count = purchases_today.count()
    purchases_today_units = PurchaseItem.objects.filter(
        invoice__in=purchases_today
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    purchases_today_value = PurchaseItem.objects.filter(
        invoice__in=purchases_today
    ).aggregate(total=Sum(F("quantity") * F("cost_price")))["total"] or Decimal("0")

    purchases_yesterday_count = purchases_qs.filter(date_received=yesterday).count()

    # -- Goods Out today --
    sales_today = sales_qs.filter(date_dispatched=today)
    sales_today_count = sales_today.count()
    sales_today_units = SaleItem.objects.filter(
        invoice__in=sales_today
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    sales_today_value = SaleItem.objects.filter(
        invoice__in=sales_today
    ).aggregate(total=Sum(F("quantity") * F("selling_price")))["total"] or Decimal("0")

    sales_yesterday_count = sales_qs.filter(date_dispatched=yesterday).count()

    # -- Today's Revenue (sales value) --
    yesterday_sales_value = SaleItem.objects.filter(
        invoice__in=sales_qs.filter(date_dispatched=yesterday)
    ).aggregate(total=Sum(F("quantity") * F("selling_price")))["total"] or Decimal("0")

    # -- Today's Purchase Cost --
    yesterday_purchase_value = PurchaseItem.objects.filter(
        invoice__in=purchases_qs.filter(date_received=yesterday)
    ).aggregate(total=Sum(F("quantity") * F("cost_price")))["total"] or Decimal("0")

    # -- Pending Payable (Supplier balances > 0) --
    payable_data = suppliers_qs.filter(balance__gt=0).aggregate(
        total=Sum("balance"), count=Count("id")
    )
    total_payable = payable_data["total"] or Decimal("0")
    payable_supplier_count = payable_data["count"] or 0

    # -- Pending Receivable (Customer balances > 0) --
    receivable_data = customers_qs.filter(balance__gt=0).aggregate(
        total=Sum("balance"), count=Count("id")
    )
    total_receivable = receivable_data["total"] or Decimal("0")
    receivable_customer_count = receivable_data["count"] or 0

    # -- Total Suppliers / Customers --
    total_suppliers = suppliers_qs.count()
    active_suppliers = suppliers_qs.filter(status="active").count()
    total_customers = customers_qs.count()
    active_customers = customers_qs.filter(status="active").count()

    # -- Payments today --
    payments_received_today = payments_qs.filter(
        date_paid=today, payment_type="received"
    ).aggregate(total=Sum("amount"), count=Count("id"))
    payments_sent_today = payments_qs.filter(
        date_paid=today, payment_type="sent"
    ).aggregate(total=Sum("amount"), count=Count("id"))

    # -- Spoilage this month --
    spoilage_this_month = spoilage_qs.filter(date_reported__gte=month_start)
    spoilage_month_count = spoilage_this_month.count()
    spoilage_month_loss = spoilage_this_month.aggregate(
        total=Sum(F("quantity") * F("price_per_unit"))
    )["total"] or Decimal("0")

    # -- Stock Value --
    stock_value = items_qs.aggregate(
        total=Sum(F("quantity_in_stock") * F("cost_price"))
    )["total"] or Decimal("0")

    # -- Unpaid Invoices --
    unpaid_purchase_count = purchases_qs.filter(payment_status="unpaid").count()
    unpaid_sale_count = sales_qs.filter(payment_status="unpaid").count()
    partial_purchase_count = purchases_qs.filter(payment_status="partial").count()
    partial_sale_count = sales_qs.filter(payment_status="partial").count()

    stat_cards = [
        {
            "key": "total_items",
            "label": "Total Items",
            "value": total_items,
            "badge": _pct_change(items_this_month, items_prev_month) + " this month",
            "badge_type": "green" if items_this_month >= items_prev_month else "red",
        },
        {
            "key": "stock_value",
            "label": "Stock Value",
            "value": f"{currency} {stock_value:,.0f}",
            "badge": f"{total_items} products",
            "badge_type": "blue",
        },
        {
            "key": "low_stock",
            "label": "Low Stock Items",
            "value": low_stock_count,
            "badge": "Need restock" if low_stock_count > 0 else "All good",
            "badge_type": "red" if low_stock_count > 0 else "green",
        },
        {
            "key": "goods_in_today",
            "label": "Goods In (Today)",
            "value": purchases_today_count,
            "badge": f"{purchases_today_units:,.0f} units received",
            "badge_type": "green",
        },
        {
            "key": "goods_out_today",
            "label": "Goods Out (Today)",
            "value": sales_today_count,
            "badge": _pct_change(sales_today_count, sales_yesterday_count) + " vs yesterday",
            "badge_type": "green" if sales_today_count >= sales_yesterday_count else "red",
        },
        {
            "key": "today_revenue",
            "label": "Today's Revenue",
            "value": f"{currency} {sales_today_value:,.0f}",
            "badge": _pct_change(sales_today_value, yesterday_sales_value) + " vs yesterday",
            "badge_type": "green" if sales_today_value >= yesterday_sales_value else "red",
        },
        {
            "key": "today_purchase",
            "label": "Today's Purchase",
            "value": f"{currency} {purchases_today_value:,.0f}",
            "badge": f"{purchases_today_count} invoices",
            "badge_type": "blue",
        },
        {
            "key": "pending_payable",
            "label": "Pending Payable",
            "value": f"{currency} {total_payable:,.0f}",
            "badge": f"{payable_supplier_count} suppliers",
            "badge_type": "amber",
        },
        {
            "key": "pending_receivable",
            "label": "Pending Receivable",
            "value": f"{currency} {total_receivable:,.0f}",
            "badge": f"{receivable_customer_count} customers",
            "badge_type": "amber",
        },
        {
            "key": "payments_received_today",
            "label": "Received Today",
            "value": f"{currency} {(payments_received_today['total'] or 0):,.0f}",
            "badge": f"{payments_received_today['count'] or 0} payments",
            "badge_type": "green",
        },
        {
            "key": "payments_sent_today",
            "label": "Sent Today",
            "value": f"{currency} {(payments_sent_today['total'] or 0):,.0f}",
            "badge": f"{payments_sent_today['count'] or 0} payments",
            "badge_type": "blue",
        },
        {
            "key": "total_suppliers",
            "label": "Suppliers",
            "value": total_suppliers,
            "badge": f"{active_suppliers} active",
            "badge_type": "green",
        },
        {
            "key": "total_customers",
            "label": "Customers",
            "value": total_customers,
            "badge": f"{active_customers} active",
            "badge_type": "green",
        },
        {
            "key": "spoilage_month",
            "label": "Spoilage (Month)",
            "value": spoilage_month_count,
            "badge": f"{currency} {spoilage_month_loss:,.0f} loss",
            "badge_type": "red" if spoilage_month_count > 0 else "green",
        },
        {
            "key": "unpaid_invoices",
            "label": "Unpaid Invoices",
            "value": unpaid_purchase_count + unpaid_sale_count,
            "badge": f"{partial_purchase_count + partial_sale_count} partial",
            "badge_type": "amber",
        },
    ]

    # ═══════════════════════════════════════════════════════════
    #  2) CHARTS DATA (last 30 days)
    # ═══════════════════════════════════════════════════════════

    days_30_ago = today - timedelta(days=29)

    # -- Sales vs Purchases vs Spoilage (daily for 30 days) --
    daily_labels = []
    daily_sales = []
    daily_purchases = []
    daily_spoilage = []

    # Pre-aggregate
    sale_by_day = {}
    for row in (
        SaleItem.objects.filter(
            invoice__company=company, invoice__is_void=False,
            invoice__date_dispatched__gte=days_30_ago
        )
        .values("invoice__date_dispatched")
        .annotate(total=Sum(F("quantity") * F("selling_price")))
    ):
        sale_by_day[row["invoice__date_dispatched"]] = float(row["total"] or 0)

    purchase_by_day = {}
    for row in (
        PurchaseItem.objects.filter(
            invoice__company=company, invoice__is_void=False,
            invoice__date_received__gte=days_30_ago
        )
        .values("invoice__date_received")
        .annotate(total=Sum(F("quantity") * F("cost_price")))
    ):
        purchase_by_day[row["invoice__date_received"]] = float(row["total"] or 0)

    spoilage_by_day = {}
    for row in (
        spoilage_qs.filter(date_reported__gte=days_30_ago)
        .values("date_reported")
        .annotate(total=Sum(F("quantity") * F("price_per_unit")))
    ):
        spoilage_by_day[row["date_reported"]] = float(row["total"] or 0)

    for i in range(30):
        d = days_30_ago + timedelta(days=i)
        daily_labels.append(d.strftime("%b %d"))
        daily_sales.append(sale_by_day.get(d, 0))
        daily_purchases.append(purchase_by_day.get(d, 0))
        daily_spoilage.append(spoilage_by_day.get(d, 0))

    # -- Payment Status Pie (all time for this company) --
    all_invoices_qs = list(purchases_qs.values_list("payment_status", flat=True)) + \
                      list(sales_qs.values_list("payment_status", flat=True))
    pay_status_counts = {"paid": 0, "partial": 0, "unpaid": 0}
    for ps in all_invoices_qs:
        if ps in pay_status_counts:
            pay_status_counts[ps] += 1

    # -- Top 5 Sold Items (by quantity, this month) --
    top_items_sold = (
        SaleItem.objects.filter(
            invoice__company=company, invoice__is_void=False,
            invoice__date_dispatched__gte=month_start
        )
        .values("item__name")
        .annotate(total_qty=Sum("quantity"))
        .order_by("-total_qty")[:5]
    )

    # -- Top 5 Customers (by sale value, this month) --
    top_customers = (
        SaleItem.objects.filter(
            invoice__company=company, invoice__is_void=False,
            invoice__date_dispatched__gte=month_start
        )
        .values("invoice__customer__name")
        .annotate(total_value=Sum(F("quantity") * F("selling_price")))
        .order_by("-total_value")[:5]
    )

    charts = {
        "trend": {
            "labels": daily_labels,
            "sales": daily_sales,
            "purchases": daily_purchases,
            "spoilage": daily_spoilage,
        },
        "payment_status": {
            "labels": ["Paid", "Partial", "Unpaid"],
            "data": [pay_status_counts["paid"], pay_status_counts["partial"], pay_status_counts["unpaid"]],
        },
        "top_items": {
            "labels": [r["item__name"] for r in top_items_sold],
            "data": [float(r["total_qty"]) for r in top_items_sold],
        },
        "top_customers": {
            "labels": [r["invoice__customer__name"] for r in top_customers],
            "data": [float(r["total_value"]) for r in top_customers],
        },
    }

    # ═══════════════════════════════════════════════════════════
    #  3) RECENT ACTIVITY (last 10 events)
    # ═══════════════════════════════════════════════════════════

    activity = []

    for inv in purchases_qs.select_related("supplier").order_by("-created_at")[:5]:
        activity.append({
            "type": "purchase",
            "icon": "📦",
            "text": f"{inv.reference_no} — Purchased from \"{inv.supplier.name}\"",
            "time": inv.created_at.isoformat(),
            "ref": inv.reference_no,
        })

    for inv in sales_qs.select_related("customer").order_by("-created_at")[:5]:
        activity.append({
            "type": "sale",
            "icon": "🚚",
            "text": f"{inv.reference_no} — Sold to \"{inv.customer.name}\"",
            "time": inv.created_at.isoformat(),
            "ref": inv.reference_no,
        })

    for pay in payments_qs.select_related("party").order_by("-created_at")[:5]:
        direction = "Received from" if pay.payment_type == "received" else "Sent to"
        activity.append({
            "type": "payment",
            "icon": "💰",
            "text": f"{pay.reference_no} — {direction} \"{pay.party.name}\" — {currency} {pay.amount:,.0f}",
            "time": pay.created_at.isoformat(),
            "ref": pay.reference_no,
        })

    for sp in spoilage_qs.select_related("item").order_by("-created_at")[:3]:
        activity.append({
            "type": "spoilage",
            "icon": "⚠️",
            "text": f"{sp.reference_no} — {sp.item.name} ({sp.get_reason_display()}) × {sp.quantity}",
            "time": sp.created_at.isoformat(),
            "ref": sp.reference_no,
        })

    # Sort all by time desc, take top 10
    activity.sort(key=lambda x: x["time"], reverse=True)
    activity = activity[:10]

    # ═══════════════════════════════════════════════════════════
    #  4) LOW STOCK ALERTS (already computed above)
    # ═══════════════════════════════════════════════════════════
    # low_stock_items is already populated, limit to 10
    low_stock_alerts = sorted(low_stock_items, key=lambda x: float(x["quantity_in_stock"]))[:10]

    # ═══════════════════════════════════════════════════════════
    #  5) GREETING
    # ═══════════════════════════════════════════════════════════
    hour = timezone.localtime().hour
    if hour < 12:
        greeting_prefix = "Good morning"
    elif hour < 17:
        greeting_prefix = "Good afternoon"
    else:
        greeting_prefix = "Good evening"

    first_name = user.first_name or user.username
    greeting = f"{greeting_prefix}, {first_name}"

    # ═══════════════════════════════════════════════════════════
    #  RESPONSE
    # ═══════════════════════════════════════════════════════════

    return JsonResponse({
        "success": True,
        "currency": currency,
        "greeting": greeting,
        "stat_cards": stat_cards,
        "charts": charts,
        "activity": activity,
        "low_stock_alerts": low_stock_alerts,
    })


# ═══════════════════════════════════════════════════════════════
#  PRINT TRANSACTION API
#  GET /api/dashboard/transactions/?date=2026-03-07
# ═══════════════════════════════════════════════════════════════

@api_login_required
def dashboard_transactions_api(request):
    """Return all transactions for a given date (for print / export)."""
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    currency = _currency_symbol(company)
    date_str = request.GET.get("date", "").strip()

    if not date_str:
        target_date = timezone.localdate()
    else:
        try:
            from datetime import date as dt_date
            parts = date_str.split("-")
            target_date = dt_date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            return JsonResponse({"success": False, "message": "Invalid date format. Use YYYY-MM-DD."}, status=400)

    # Purchases on that date
    purchases = []
    for inv in PurchaseInvoice.objects.filter(company=company, is_void=False, date_received=target_date).select_related("supplier"):
        lines = []
        inv_total = Decimal("0")
        for line in inv.lines.select_related("item", "item__unit"):
            lt = line.quantity * line.cost_price
            inv_total += lt
            lines.append({
                "item": line.item.name,
                "unit": line.item.unit.short_name if line.item.unit else "",
                "qty": str(line.quantity),
                "price": str(line.cost_price),
                "total": str(lt),
            })
        purchases.append({
            "ref": inv.reference_no,
            "supplier": inv.supplier.name,
            "status": inv.payment_status,
            "total": str(inv_total),
            "lines": lines,
        })

    # Sales on that date
    sales = []
    for inv in SaleInvoice.objects.filter(company=company, is_void=False, date_dispatched=target_date).select_related("customer"):
        lines = []
        inv_total = Decimal("0")
        for line in inv.lines.select_related("item", "item__unit"):
            lt = line.quantity * line.selling_price
            inv_total += lt
            lines.append({
                "item": line.item.name,
                "unit": line.item.unit.short_name if line.item.unit else "",
                "qty": str(line.quantity),
                "price": str(line.selling_price),
                "total": str(lt),
            })
        sales.append({
            "ref": inv.reference_no,
            "customer": inv.customer.name,
            "status": inv.payment_status,
            "total": str(inv_total),
            "lines": lines,
        })

    # Payments on that date
    payments_list = []
    for pay in Payment.objects.filter(company=company, is_void=False, date_paid=target_date).select_related("party"):
        payments_list.append({
            "ref": pay.reference_no,
            "type": pay.payment_type,
            "party": pay.party.name,
            "method": pay.payment_method,
            "amount": str(pay.amount),
        })

    # Spoilage on that date
    spoilage_list = []
    for sp in SpoilageLoss.objects.filter(company=company, is_void=False, date_reported=target_date).select_related("item"):
        spoilage_list.append({
            "ref": sp.reference_no,
            "item": sp.item.name,
            "reason": sp.get_reason_display(),
            "qty": str(sp.quantity),
            "loss": str(sp.quantity * sp.price_per_unit),
        })

    return JsonResponse({
        "success": True,
        "date": str(target_date),
        "currency": currency,
        "company_name": company.name,
        "purchases": purchases,
        "sales": sales,
        "payments": payments_list,
        "spoilage": spoilage_list,
    })