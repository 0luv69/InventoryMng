"""
Supplier JSON API views.

Endpoints:
    GET  /api/suppliers/list/     → paginated list + stats + search/filter/sort
    POST /api/suppliers/create/   → create new supplier
    POST /api/suppliers/update/   → update existing supplier
    POST /api/suppliers/delete/   → soft delete (is_removed=True, status=inactive)
"""

import json
from decimal import Decimal

from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q, Sum, Count
from django.utils import timezone

from ..models import Party
from ..decorators import api_login_required,company_required


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _serialize_supplier(s):
    """Convert a Party (supplier) instance to a JSON-safe dict."""
    return {
        "id": s.id,
        "uuid": str(s.uuid),
        "name": s.name,
        "contact_person": s.contact_person,
        "phone": s.phone,
        "email": s.email,
        "address": s.address,
        "notes": s.notes,
        "balance": str(s.balance),
        "total_amount": str(s.total_amount),
        "status": s.status,
        "created_at": s.created_at.strftime("%Y-%m-%d"),
        "updated_at": s.updated_at.strftime("%Y-%m-%d"),
    }


def _get_supplier_base_qs(company):
    """Base queryset for all non-removed suppliers of a company."""
    return Party.objects.filter(
        company=company,
        party_type=Party.PartyType.SUPPLIER,
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


@company_required
def suppliers_page(request):
    """Render the suppliers HTML page (data loaded via JS/API)."""
    context = {
        "title": "Suppliers",
        "userProfile": request.userProfile,
    }
    return render(request, "core/suppliers.html", context)

# ═══════════════════════════════════════════════════════════════
#  LIST  (GET)
#  Params: ?search=&status=&balance=&sort=&order=&page=&per_page=
# ══════════════════════════════════════════���════════════════════

@api_login_required
def supplier_list_api(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    base_qs = _get_supplier_base_qs(company)

    # ── Stats (calculated from full dataset, before filters) ──
    stats = base_qs.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status="active")),
        total_payable=Sum("balance", filter=Q(balance__gt=0)),
        total_paid=Sum("total_amount"),
    )

    overview = {
        "total_suppliers": stats["total"] or 0,
        "active_suppliers": stats["active"] or 0,
        "total_payable": str(stats["total_payable"] or Decimal("0.00")),
        "total_paid_lifetime": str(stats["total_paid"] or Decimal("0.00")),
    }

    # ── Filters ──
    qs = base_qs

    # Search (name, phone, email)
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
    elif balance_filter == "overpaid":
        qs = qs.filter(balance__lt=0)

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

    suppliers = qs[start: start + per_page]

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
        "suppliers": [_serialize_supplier(s) for s in suppliers],
    })


# ═══════════════════════════════════════════════════════════════
#  CREATE  (POST)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def supplier_create_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"success": False, "message": "Supplier name is required."}, status=400)

    # Check duplicate
    company = request.company
    if _get_supplier_base_qs(company).filter(name__iexact=name).exists():
        return JsonResponse(
            {"success": False, "message": f'Supplier "{name}" already exists.'},
            status=400,
        )

    supplier = Party.objects.create(
        company=company,
        party_type=Party.PartyType.SUPPLIER,
        name=name,
        contact_person=(data.get("contact_person") or "").strip(),
        phone=(data.get("phone") or "").strip(),
        email=(data.get("email") or "").strip(),
        address=(data.get("address") or "").strip(),
        description=(data.get("description") or "").strip(),
        notes=(data.get("notes") or "").strip(),
        status=data.get("status", "active") if data.get("status") in ("active", "inactive") else "active",
    )

    return JsonResponse({
        "success": True,
        "message": f'Supplier "{name}" created successfully.',
        "supplier": _serialize_supplier(supplier),
    }, status=201)


# ═══════════════════════════════════════════════════════════════
#  UPDATE  (POST)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def supplier_update_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    supplier_id = data.get("id")
    if not supplier_id:
        return JsonResponse({"success": False, "message": "Supplier ID is required."}, status=400)

    company = request.company
    try:
        supplier = _get_supplier_base_qs(company).get(id=supplier_id)
    except Party.DoesNotExist:
        return JsonResponse({"success": False, "message": "Supplier not found."}, status=404)

    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"success": False, "message": "Supplier name is required."}, status=400)

    # Check duplicate (exclude self)
    if _get_supplier_base_qs(company).filter(name__iexact=name).exclude(id=supplier_id).exists():
        return JsonResponse(
            {"success": False, "message": f'Supplier "{name}" already exists.'},
            status=400,
        )

    supplier.name = name
    supplier.contact_person = (data.get("contact_person") or "").strip()
    supplier.phone = (data.get("phone") or "").strip()
    supplier.email = (data.get("email") or "").strip()
    supplier.address = (data.get("address") or "").strip()
    supplier.notes = (data.get("notes") or "").strip()

    new_status = data.get("status", "").strip()
    if new_status in ("active", "inactive"):
        supplier.status = new_status

    supplier.save()

    return JsonResponse({
        "success": True,
        "message": f'Supplier "{name}" updated successfully.',
        "supplier": _serialize_supplier(supplier),
    })


# ═══════════════════════════════════════════════════════════════
#  DELETE / VOID  (POST)
# ══════════════════════════���════════════════════════════════════

@api_login_required
def supplier_delete_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    # Support single or bulk delete
    supplier_ids = data.get("ids", [])
    single_id = data.get("id")
    if single_id and not supplier_ids:
        supplier_ids = [single_id]

    if not supplier_ids:
        return JsonResponse({"success": False, "message": "Supplier ID(s) required."}, status=400)

    company = request.company
    suppliers = _get_supplier_base_qs(company).filter(id__in=supplier_ids)
    count = suppliers.count()

    if count == 0:
        return JsonResponse({"success": False, "message": "No matching suppliers found."}, status=404)

    # Soft delete: set is_removed=True and status=inactive
    suppliers.update(
        is_removed=True,
        status=Party.Status.INACTIVE,
        updated_at=timezone.now(),
    )

    label = "supplier" if count == 1 else "suppliers"
    return JsonResponse({
        "success": True,
        "message": f"{count} {label} deleted successfully.",
        "deleted_ids": list(supplier_ids),
    })