"""
Customer JSON API views.

Endpoints:
    GET  /api/customers/list/     → paginated list + stats + search/filter/sort
    POST /api/customers/create/   → create new customer
    POST /api/customers/update/   → update existing customer
    POST /api/customers/delete/   → soft delete (is_removed=True, status=inactive)
"""

import json
import os
from decimal import Decimal

from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.conf import settings

from ..models import Party, SaleInvoice, Payment
from ..decorators import api_login_required, company_required

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _serialize_customer(c):
    """Convert a Party (customer) instance to a JSON-safe dict."""
    return {
        "id": c.id,
        "uuid": str(c.uuid),
        "name": c.name,
        "contact_person": c.contact_person,
        "phone": c.phone,
        "email": c.email,
        "address": c.address,
        "notes": c.notes,
        "balance": str(c.balance),
        "total_amount": str(c.total_amount),
        "status": c.status,
        "logo": c.logo.url if c.logo else "",
        "created_at": c.created_at.strftime("%Y-%m-%d"),
        "updated_at": c.updated_at.strftime("%Y-%m-%d"),
    }


def _get_customer_base_qs(company):
    """Base queryset for all non-removed customers of a company."""
    return Party.objects.filter(
        company=company,
        party_type=Party.PartyType.CUSTOMER,
        is_removed=False,
    )


def _parse_json(request):
    """Parse JSON body, return (dict, None) or (None, JsonResponse)."""
    try:
        data = json.loads(request.body.decode("utf-8"))
        return data, None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse(
            {"success": False, "message": "Invalid JSON."}, status=400
        )


def _parse_multipart(request):
    """Extract fields from multipart/form-data (for logo upload)."""
    return {
        "name": request.POST.get("name", "").strip(),
        "contact_person": request.POST.get("contact_person", "").strip(),
        "phone": request.POST.get("phone", "").strip(),
        "email": request.POST.get("email", "").strip(),
        "address": request.POST.get("address", "").strip(),
        "notes": request.POST.get("notes", "").strip(),
        "status": request.POST.get("status", "active").strip(),
        "id": request.POST.get("id", "").strip(),
        "remove_logo": request.POST.get("remove_logo", "").strip(),
    }


@company_required
def customers_page(request):
    """Render the customers HTML page (data loaded via JS/API)."""
    context = {
        "title": "Customers",
        "userProfile": request.userProfile,
    }
    return render(request, "core/customers.html", context)


# ═══════════════════════════════════════════════════════════════
#  LIST  (GET)
#  Params: ?search=&status=&balance=&sort=&order=&page=&per_page=
# ═══════════════════════════════════════════════════════════════

@api_login_required
def customer_list_api(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    base_qs = _get_customer_base_qs(company)

    # ── Stats (calculated from full dataset, before filters) ──
    stats = base_qs.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status="active")),
        total_receivable=Sum("balance", filter=Q(balance__gt=0)),
        total_received=Sum("total_amount"),
    )

    overview = {
        "total_customers": stats["total"] or 0,
        "active_customers": stats["active"] or 0,
        "total_receivable": str(stats["total_receivable"] or Decimal("0.00")),
        "total_received_lifetime": str(stats["total_received"] or Decimal("0.00")),
    }

    # ── Filters ──
    qs = base_qs

    # Search (name, phone, email, contact_person)
    search = request.GET.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
            | Q(contact_person__icontains=search)
        )

    # Status filter
    status = request.GET.get("status", "").strip()
    if status in ("active", "inactive"):
        qs = qs.filter(status=status)

    # Balance filter
    balance_filter = request.GET.get("balance", "").strip()
    if balance_filter == "has-balance":
        qs = qs.filter(balance__gt=0)
    elif balance_filter == "no-balance":
        qs = qs.filter(balance__lte=0)

    # ── Sort ──
    sort = request.GET.get("sort", "created_at").strip()
    order = request.GET.get("order", "desc").strip()
    prefix = "-" if order == "desc" else ""

    sort_map = {
        "name": "name",
        "created_at": "created_at",
        "balance": "balance",
    }
    order_field = sort_map.get(sort, "created_at")
    qs = qs.order_by(f"{prefix}{order_field}")

    # ── Pagination ──
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = min(100, max(1, int(request.GET.get("per_page", 10))))
    except (ValueError, TypeError):
        per_page = 10

    total = qs.count()
    total_pages = max(1, -(-total // per_page))  # ceil division
    page = min(page, total_pages)
    start = (page - 1) * per_page

    customers = qs[start: start + per_page]

    return JsonResponse({
        "success": True,
        "overview": overview,
        "filters_applied": {
            "search": search,
            "status": status,
            "balance": balance_filter,
            "sort": sort,
            "order": order,
        },
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
        "customers": [_serialize_customer(c) for c in customers],
    })


# ═══════════════════════════════════════════════════════════════
#  CREATE  (POST — multipart/form-data for logo support)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def customer_create_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data = _parse_multipart(request)
    name = data["name"]

    if not name:
        return JsonResponse({"success": False, "message": "Customer name is required."}, status=400)

    company = request.company
    if _get_customer_base_qs(company).filter(name__iexact=name).exists():
        return JsonResponse(
            {"success": False, "message": f'Customer "{name}" already exists.'},
            status=400,
        )

    customer = Party(
        company=company,
        party_type=Party.PartyType.CUSTOMER,
        name=name,
        contact_person=data["contact_person"],
        phone=data["phone"],
        email=data["email"],
        address=data["address"],
        notes=data["notes"],
        status=data["status"] if data["status"] in ("active", "inactive") else "active",
    )

    # Handle logo upload
    logo_file = request.FILES.get("logo")
    if logo_file:
        customer.logo = logo_file

    customer.save()

    return JsonResponse({
        "success": True,
        "message": f'Customer "{name}" created successfully.',
        "customer": _serialize_customer(customer),
    }, status=201)


# ═══════════════════════════════════════════════════════════════
#  UPDATE  (POST — multipart/form-data for logo support)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def customer_update_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data = _parse_multipart(request)
    customer_id = data["id"]

    if not customer_id:
        return JsonResponse({"success": False, "message": "Customer ID is required."}, status=400)

    company = request.company
    try:
        customer = _get_customer_base_qs(company).get(id=customer_id)
    except Party.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

    name = data["name"]
    if not name:
        return JsonResponse({"success": False, "message": "Customer name is required."}, status=400)

    # Check duplicate (exclude self)
    if _get_customer_base_qs(company).filter(name__iexact=name).exclude(id=customer_id).exists():
        return JsonResponse(
            {"success": False, "message": f'Customer "{name}" already exists.'},
            status=400,
        )

    customer.name = name
    customer.contact_person = data["contact_person"]
    customer.phone = data["phone"]
    customer.email = data["email"]
    customer.address = data["address"]
    customer.notes = data["notes"]

    new_status = data["status"]
    if new_status in ("active", "inactive"):
        customer.status = new_status

    # Handle logo
    logo_file = request.FILES.get("logo")
    if logo_file:
        # Remove old logo file if exists
        if customer.logo:
            old_path = os.path.join(settings.MEDIA_ROOT, customer.logo.name)
            if os.path.isfile(old_path):
                os.remove(old_path)
        customer.logo = logo_file
    elif data["remove_logo"] == "1":
        # User explicitly removed logo
        if customer.logo:
            old_path = os.path.join(settings.MEDIA_ROOT, customer.logo.name)
            if os.path.isfile(old_path):
                os.remove(old_path)
            customer.logo = None

    customer.save()

    return JsonResponse({
        "success": True,
        "message": f'Customer "{name}" updated successfully.',
        "customer": _serialize_customer(customer),
    })


# ═════════════════════════════════════════════════════════���═════
#  DELETE / VOID  (POST — JSON body)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def customer_delete_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    # Support single or bulk delete
    customer_ids = data.get("ids", [])
    single_id = data.get("id")
    if single_id and not customer_ids:
        customer_ids = [single_id]

    if not customer_ids:
        return JsonResponse({"success": False, "message": "Customer ID(s) required."}, status=400)

    company = request.company
    customers = _get_customer_base_qs(company).filter(id__in=customer_ids)
    count = customers.count()

    if count == 0:
        return JsonResponse({"success": False, "message": "No matching customers found."}, status=404)

    # Soft delete: set is_removed=True and status=inactive
    customers.update(
        is_removed=True,
        status=Party.Status.INACTIVE,
        updated_at=timezone.now(),
    )

    label = "customer" if count == 1 else "customers"
    return JsonResponse({
        "success": True,
        "message": f"{count} {label} deleted successfully.",
        "deleted_ids": list(customer_ids),
    })


# ═══════════════════════════════════════════════════════════════
#  CUSTOMER TRANSACTIONS  (GET)
#  Returns latest 5 sale invoices + latest 5 payments for a customer
# ═══════════════════════════════════════════════════════════════

@api_login_required
def customer_transactions_api(request, pk):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    try:
        customer = _get_customer_base_qs(company).get(id=pk)
    except Party.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

    # ── Sale Invoices (latest 5, non-voided) ──
    invoices_qs = SaleInvoice.objects.filter(
        company=company, customer=customer, is_void=False
    ).order_by("-date_dispatched", "-created_at")[:5]

    total_invoices = SaleInvoice.objects.filter(
        company=company, customer=customer, is_void=False
    ).count()

    invoices = []
    for inv in invoices_qs:
        invoices.append({
            "id": inv.id,
            "reference_no": inv.reference_no,
            "date": inv.date_dispatched.strftime("%Y-%m-%d"),
            "total": str(inv.invoice_total),
            "paid": str(inv.total_paid),
            "balance": str(inv.balance_due),
            "payment_status": inv.payment_status,
        })

    # ── Payments received (latest 5, non-voided) ──
    payments_qs = Payment.objects.filter(
        company=company,
        party=customer,
        payment_type=Payment.PaymentType.RECEIVED,
        is_void=False,
    ).select_related("sale_invoice").order_by("-date_paid", "-created_at")[:5]

    total_payments = Payment.objects.filter(
        company=company,
        party=customer,
        payment_type=Payment.PaymentType.RECEIVED,
        is_void=False,
    ).count()

    payments = []
    for pay in payments_qs:
        payments.append({
            "id": pay.id,
            "reference_no": pay.reference_no,
            "date": pay.date_paid.strftime("%Y-%m-%d"),
            "amount": str(pay.amount),
            "payment_method": pay.payment_method,
            "linked_invoice": pay.sale_invoice.reference_no if pay.sale_invoice else "",
        })

    return JsonResponse({
        "success": True,
        "invoices": invoices,
        "payments": payments,
        "total_invoices": total_invoices,
        "total_payments": total_payments,
    })



# ═══════════════════════════════════════════════════════════════
#  CUSTOMER PROFILE PAGE  (GET)
#  Renders the full customer profile page
# ═══════════════════════════════════════════════════════════════

@company_required
def customer_profile_page(request, pk):
    """Render the full customer profile page."""
    company = request.userProfile.company
    try:
        customer = _get_customer_base_qs(company).get(id=pk)
    except Party.DoesNotExist:
        from django.http import Http404
        raise Http404("Customer not found.")

    context = {
        "title": f"{customer.name} — Customer Profile",
        "userProfile": request.userProfile,
        "customer": customer,
    }
    return render(request, "core/customer_profile.html", context)


# ═══════════════════════════════════════════════════════════════
#  CUSTOMER STATEMENT API  (GET)
#  Full ledger: all sale invoices + all payments, sorted by date,
#  with running balance. Supports ?from_date=&to_date= filters.
# ═══════════════════════════════════════════════════════════════

@api_login_required
def customer_statement_api(request, pk):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    try:
        customer = _get_customer_base_qs(company).get(id=pk)
    except Party.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

    # ── Date filters ──
    from datetime import datetime
    from_date_str = request.GET.get("from_date", "").strip()
    to_date_str = request.GET.get("to_date", "").strip()

    from_date = None
    to_date = None
    try:
        if from_date_str:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        if to_date_str:
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"success": False, "message": "Invalid date format. Use YYYY-MM-DD."}, status=400)

    # ── Fetch all non-voided Sale Invoices ──
    invoices_qs = SaleInvoice.objects.filter(
        company=company, customer=customer, is_void=False
    )
    if from_date:
        invoices_qs = invoices_qs.filter(date_dispatched__gte=from_date)
    if to_date:
        invoices_qs = invoices_qs.filter(date_dispatched__lte=to_date)

    # ── Fetch all non-voided Payments ──
    payments_qs = Payment.objects.filter(
        company=company,
        party=customer,
        payment_type=Payment.PaymentType.RECEIVED,
        is_void=False,
    ).select_related("sale_invoice")
    if from_date:
        payments_qs = payments_qs.filter(date_paid__gte=from_date)
    if to_date:
        payments_qs = payments_qs.filter(date_paid__lte=to_date)

    # ── Build the ledger entries ──
    entries = []

    for inv in invoices_qs:
        entries.append({
            "date": inv.date_dispatched.strftime("%Y-%m-%d"),
            "type": "invoice",
            "reference_no": inv.reference_no,
            "description": f"Sale Invoice #{inv.reference_no}",
            "debit": str(inv.invoice_total),   # customer owes more
            "credit": "0",
            "id": inv.id,
        })

    for pay in payments_qs:
        entries.append({
            "date": pay.date_paid.strftime("%Y-%m-%d"),
            "type": "payment",
            "reference_no": pay.reference_no,
            "description": f"Payment Received — {pay.get_payment_method_display()}"
                           + (f" (Inv #{pay.sale_invoice.reference_no})" if pay.sale_invoice else ""),
            "debit": "0",
            "credit": str(pay.amount),         # customer paid
            "id": pay.id,
        })

    # ── Sort by date ascending, then by type (invoice before payment on same day) ──
    type_order = {"invoice": 0, "payment": 1}
    entries.sort(key=lambda e: (e["date"], type_order.get(e["type"], 0)))

    # ── Calculate running balance ──
    running_balance = Decimal("0.00")
    for entry in entries:
        debit = Decimal(entry["debit"])
        credit = Decimal(entry["credit"])
        running_balance += debit - credit
        entry["running_balance"] = str(running_balance)

    # ── Summary ──
    total_debit = sum(Decimal(e["debit"]) for e in entries)
    total_credit = sum(Decimal(e["credit"]) for e in entries)
    closing_balance = total_debit - total_credit

    return JsonResponse({
        "success": True,
        "customer": {
            "id": customer.id,
            "name": customer.name,
        },
        "filters": {
            "from_date": from_date_str,
            "to_date": to_date_str,
        },
        "summary": {
            "total_invoiced": str(total_debit),
            "total_paid": str(total_credit),
            "closing_balance": str(closing_balance),
            "total_entries": len(entries),
        },
        "entries": entries,
    })