"""
Spoilage & Loss JSON API views.

Endpoints:
    GET  /api/spoilage/list/           → paginated list + stats + search/filter/sort
    POST /api/spoilage/create/         → create new record (auto ref_no, auto deduct stock)
    POST /api/spoilage/update/<pk>/    → update record (adjust stock diff)
    POST /api/spoilage/void/<pk>/      → soft void (restore stock)
    POST /api/spoilage/bulk-void/      → bulk soft void

    GET  /api/spoilage/helpers/items/  → item search for dropdown
    GET  /api/spoilage/helpers/users/  → company users for "reported by" dropdown
"""

import json
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.db.models import Q, Sum, Count, F
from django.utils import timezone
from django.contrib.auth import get_user_model

from ..models import SpoilageLoss, Item, UserProfile
from ..decorators import api_login_required

User = get_user_model()


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _serialize_record(r):
    """Convert a SpoilageLoss instance to a JSON-safe dict."""
    return {
        "id": r.id,
        "reference_no": r.reference_no,
        "item_id": r.item_id,
        "item_name": r.item.name if r.item else "",
        "item_unit": r.item.unit.short_name if r.item and r.item.unit else "",
        "item_cost_price": str(r.item.cost_price) if r.item else "0",
        "reason": r.reason,
        "reason_display": r.get_reason_display(),
        "quantity": str(r.quantity),
        "price_per_unit": str(r.price_per_unit),
        "total_loss": str(r.total_loss),
        "date_reported": r.date_reported.strftime("%Y-%m-%d") if hasattr(r.date_reported, 'strftime') else str(r.date_reported),
        "reported_by_id": r.reported_by_id,
        "reported_by_name": (
            r.reported_by.get_full_name() or r.reported_by.username
        ) if r.reported_by else "",
        "notes": r.notes,
        "is_void": r.is_void,
        "void_reason": r.void_reason,
        "created_at": r.created_at.strftime("%Y-%m-%d"),
    }


def _base_qs(company):
    """Non-voided spoilage records for a company."""
    return SpoilageLoss.objects.filter(
        company=company,
    ).select_related("item", "item__unit", "reported_by")


def _parse_json(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        return data, None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse(
            {"success": False, "message": "Invalid JSON."}, status=400
        )


def _safe_decimal(val, default="0"):
    try:
        d = Decimal(val)
        return d if d >= 0 else Decimal(default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _next_ref(company):
    """Generate next reference number like SPL-0001."""
    last = (
        SpoilageLoss.objects.filter(company=company)
        .order_by("-id")
        .values_list("reference_no", flat=True)
        .first()
    )
    if last and last.startswith("SPL-"):
        try:
            num = int(last.split("-")[1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"SPL-{num:04d}"


# ═══════════════════════════════════════════════════════════════
#  LIST  (GET)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def spoilage_list_api(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    base = _base_qs(company).filter(is_void=False)

    # ── Stats (before filters) ──
    stats = base.aggregate(
        total_records=Count("id"),
        total_units=Sum("quantity"),
        total_loss=Sum(F("quantity") * F("price_per_unit")),
    )

    now = timezone.now()
    this_month_count = base.filter(
        date_reported__year=now.year,
        date_reported__month=now.month,
    ).count()

    voided_count = _base_qs(company).filter(is_void=True).count()

    overview = {
        "total_records": stats["total_records"] or 0,
        "total_units": str(stats["total_units"] or 0),
        "total_loss": str(stats["total_loss"] or Decimal("0.00")),
        "this_month": this_month_count,
        "voided": voided_count,
    }

    # ── Filters ──
    qs = base

    # Reason filter
    reason = request.GET.get("reason", "").strip()
    if reason and reason != "all":
        qs = qs.filter(reason=reason)

    # Search
    search = request.GET.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(item__name__icontains=search)
            | Q(notes__icontains=search)
            | Q(reference_no__icontains=search)
            | Q(reported_by__first_name__icontains=search)
            | Q(reported_by__last_name__icontains=search)
            | Q(reported_by__username__icontains=search)
        )

    # Date range
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    if date_from:
        qs = qs.filter(date_reported__gte=date_from)
    if date_to:
        qs = qs.filter(date_reported__lte=date_to)

    # ── Sort ──
    sort = request.GET.get("sort", "date_reported").strip()
    order = request.GET.get("order", "desc").strip()
    prefix = "-" if order == "desc" else ""

    sort_map = {
        "date": "date_reported",
        "date_reported": "date_reported",
        "qty": "quantity",
        "quantity": "quantity",
        "lossValue": "price_per_unit",
        "item": "item__name",
    }
    order_field = sort_map.get(sort, "date_reported")
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
    total_pages = max(1, -(-total // per_page))
    page = min(page, total_pages)
    start = (page - 1) * per_page

    records = qs[start: start + per_page]

    return JsonResponse({
        "success": True,
        "overview": overview,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
        "records": [_serialize_record(r) for r in records],
    })


# ═══════════════════════════════════════════════════════════════
#  CREATE  (POST — JSON)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def spoilage_create_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company

    # Validate item
    item_id = data.get("item_id")
    if not item_id:
        return JsonResponse({"success": False, "message": "Item is required."}, status=400)
    try:
        item = Item.objects.select_related("unit").get(id=item_id, company=company, is_active=True)
    except Item.DoesNotExist:
        return JsonResponse({"success": False, "message": "Item not found."}, status=404)

    # Validate reason
    reason = data.get("reason", "").strip()
    valid_reasons = [c[0] for c in SpoilageLoss.Reason.choices]
    if reason not in valid_reasons:
        return JsonResponse({"success": False, "message": "Invalid reason."}, status=400)

    # Validate quantity
    qty = _safe_decimal(data.get("quantity", 0))
    if qty <= 0:
        return JsonResponse({"success": False, "message": "Quantity must be greater than 0."}, status=400)

    price = _safe_decimal(data.get("price_per_unit", item.cost_price))

    # Reported by (default = logged-in user)
    reported_by_id = data.get("reported_by_id")
    if reported_by_id:
        try:
            reported_user = User.objects.get(id=reported_by_id)
            # Verify user belongs to same company
            UserProfile.objects.get(user=reported_user, company=company)
        except (User.DoesNotExist, UserProfile.DoesNotExist):
            reported_user = request.user
    else:
        reported_user = request.user

    date_reported = data.get("date_reported", "").strip()
    if not date_reported:
        date_reported = timezone.now().date()

    notes = data.get("notes", "").strip()

    ref = _next_ref(company)

    record = SpoilageLoss.objects.create(
        company=company,
        reference_no=ref,
        item=item,
        reason=reason,
        quantity=qty,
        price_per_unit=price,
        date_reported=date_reported,
        reported_by=reported_user,
        notes=notes,
    )

    # Deduct stock
    item.quantity_in_stock = max(Decimal("0"), item.quantity_in_stock - qty)
    item.save(update_fields=["quantity_in_stock", "updated_at"])

    return JsonResponse({
        "success": True,
        "message": f'{qty} × "{item.name}" recorded as {record.get_reason_display()}. Stock deducted.',
        "record": _serialize_record(record),
    }, status=201)


# ═══════════════════════════════════════════════════════════════
#  UPDATE  (POST — JSON)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def spoilage_update_api(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company
    try:
        record = _base_qs(company).get(id=pk, is_void=False)
    except SpoilageLoss.DoesNotExist:
        return JsonResponse({"success": False, "message": "Record not found."}, status=404)

    old_qty = record.quantity
    old_item = record.item

    # Validate item
    item_id = data.get("item_id", record.item_id)
    try:
        item = Item.objects.select_related("unit").get(id=item_id, company=company, is_active=True)
    except Item.DoesNotExist:
        return JsonResponse({"success": False, "message": "Item not found."}, status=404)

    # Validate reason
    reason = data.get("reason", record.reason).strip()
    valid_reasons = [c[0] for c in SpoilageLoss.Reason.choices]
    if reason not in valid_reasons:
        return JsonResponse({"success": False, "message": "Invalid reason."}, status=400)

    qty = _safe_decimal(data.get("quantity", str(record.quantity)))
    if qty <= 0:
        return JsonResponse({"success": False, "message": "Quantity must be greater than 0."}, status=400)

    price = _safe_decimal(data.get("price_per_unit", str(record.price_per_unit)))

    # Reported by
    reported_by_id = data.get("reported_by_id")
    if reported_by_id:
        try:
            reported_user = User.objects.get(id=reported_by_id)
            UserProfile.objects.get(user=reported_user, company=company)
        except (User.DoesNotExist, UserProfile.DoesNotExist):
            reported_user = record.reported_by
    else:
        reported_user = record.reported_by

    date_reported = data.get("date_reported", "").strip() or record.date_reported
    notes = data.get("notes", "").strip()

    # Restore old stock
    old_item.quantity_in_stock += old_qty
    old_item.save(update_fields=["quantity_in_stock", "updated_at"])

    # Update record
    record.item = item
    record.reason = reason
    record.quantity = qty
    record.price_per_unit = price
    record.reported_by = reported_user
    record.date_reported = date_reported
    record.notes = notes
    record.save()

    # Deduct new stock
    item.refresh_from_db()
    item.quantity_in_stock = max(Decimal("0"), item.quantity_in_stock - qty)
    item.save(update_fields=["quantity_in_stock", "updated_at"])

    return JsonResponse({
        "success": True,
        "message": f"Record updated — stock adjusted.",
        "record": _serialize_record(record),
    })


# ═══════════════════════════════════════════════════════════════
#  VOID (single)  (POST — JSON)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def spoilage_void_api(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company
    try:
        record = _base_qs(company).get(id=pk, is_void=False)
    except SpoilageLoss.DoesNotExist:
        return JsonResponse({"success": False, "message": "Record not found."}, status=404)

    void_reason = data.get("void_reason", "Deleted by user").strip()

    # Restore stock
    item = record.item
    item.quantity_in_stock += record.quantity
    item.save(update_fields=["quantity_in_stock", "updated_at"])

    record.is_void = True
    record.void_reason = void_reason
    record.save(update_fields=["is_void", "void_reason", "updated_at"])

    return JsonResponse({
        "success": True,
        "message": "Record deleted — stock restored.",
    })


# ═══════════════════════════════════════════════════════════════
#  BULK VOID  (POST — JSON)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def spoilage_bulk_void_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    ids = data.get("ids", [])
    if not ids:
        return JsonResponse({"success": False, "message": "No IDs provided."}, status=400)

    company = request.company
    records = _base_qs(company).filter(id__in=ids, is_void=False)
    count = 0

    for record in records:
        item = record.item
        item.quantity_in_stock += record.quantity
        item.save(update_fields=["quantity_in_stock", "updated_at"])

        record.is_void = True
        record.void_reason = "Bulk deleted by user"
        record.save(update_fields=["is_void", "void_reason", "updated_at"])
        count += 1

    if count == 0:
        return JsonResponse({"success": False, "message": "No matching records."}, status=404)

    label = "record" if count == 1 else "records"
    return JsonResponse({
        "success": True,
        "message": f"{count} {label} deleted — stock restored.",
    })


# ═══════════════════════════════════════════════════════════════
#  HELPERS — Items search
# ═══════════════════════════════════════════════════════════════

@api_login_required
def spoilage_helpers_items(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    q = request.GET.get("q", "").strip()
    qs = Item.objects.filter(company=company, is_active=True).select_related("unit")
    if q:
        qs = qs.filter(Q(name__icontains=q))
    qs = qs.order_by("name")[:15]

    return JsonResponse({
        "success": True,
        "items": [
            {
                "id": i.id,
                "name": i.name,
                "unit": i.unit.short_name if i.unit else "",
                "cost_price": str(i.cost_price),
                "stock": str(i.quantity_in_stock),
            }
            for i in qs
        ],
    })


# ═══════════════════════════════════════════════════════════════
#  HELPERS — Users (for "reported by" dropdown)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def spoilage_helpers_users(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    profiles = UserProfile.objects.filter(company=company).select_related("user")

    return JsonResponse({
        "success": True,
        "current_user_id": request.user.id,
        "users": [
            {
                "id": p.user.id,
                "name": p.user.get_full_name() or p.user.username,
                "role": p.get_role_display(),
            }
            for p in profiles
        ],
    })