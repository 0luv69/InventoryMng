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

from ..models import Party
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