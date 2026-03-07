"""
Item / Product JSON API views.

Endpoints:
    GET  /api/items/list/     → paginated list + stats + search/filter/sort
    POST /api/items/create/   → create new item (multipart for logo)
    POST /api/items/update/   → update existing item (multipart for logo)
    POST /api/items/delete/   → soft delete (is_active=False)
"""

import json
import os
from decimal import Decimal, InvalidOperation

from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q, Sum, Count, F
from django.utils import timezone
from django.conf import settings

from ..models import Item, Unit
from ..decorators import api_login_required, company_required


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _serialize_item(item):
    """Convert an Item instance to a JSON-safe dict."""
    return {
        "id": item.id,
        "uuid": str(item.uuid),
        "name": item.name,
        "description": item.description,
        "logo": item.logo.url if item.logo else "",
        "unit_id": item.unit_id,
        "unit_name": item.unit.name if item.unit else "",
        "unit_short": item.unit.short_name if item.unit else "",
        "cost_price": str(item.cost_price),
        "selling_price": str(item.selling_price),
        "quantity_in_stock": str(item.quantity_in_stock),
        "low_stock_threshold": item.low_stock_threshold,
        "effective_low_stock_threshold": item.effective_low_stock_threshold,
        "is_low_stock": item.is_low_stock,
        "is_active": item.is_active,
        "created_at": item.created_at.strftime("%Y-%m-%d"),
        "updated_at": item.updated_at.strftime("%Y-%m-%d"),
    }


def _get_item_base_qs(company):
    """Base queryset: all active (non-deleted) items of a company."""
    return Item.objects.filter(
        company=company,
    ).select_related("unit")


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
    """Extract fields from multipart/form-data."""
    return {
        "name": request.POST.get("name", "").strip(),
        "description": request.POST.get("description", "").strip(),
        "unit_id": request.POST.get("unit_id", "").strip(),
        "cost_price": request.POST.get("cost_price", "0").strip(),
        "selling_price": request.POST.get("selling_price", "0").strip(),
        "quantity_in_stock": request.POST.get("quantity_in_stock", "0").strip(),
        "low_stock_threshold": request.POST.get("low_stock_threshold", "0").strip(),
        "is_active": request.POST.get("is_active", "true").strip(),
        "id": request.POST.get("id", "").strip(),
        "remove_logo": request.POST.get("remove_logo", "").strip(),
    }


def _safe_decimal(val, default="0"):
    """Safely convert to Decimal."""
    try:
        d = Decimal(val)
        return d if d >= 0 else Decimal(default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _safe_int(val, default=0):
    """Safely convert to int."""
    try:
        v = int(val)
        return v if v >= 0 else default
    except (ValueError, TypeError):
        return default

 
# ═══════════════════════════════════════════════════════════════
#  PAGE RENDER
# ═══════════════════════════════════════════════════════════════

@company_required
def items_page(request):
    """Render the items HTML page. Pass units for the dropdown."""
    company = request.userProfile.company
    units = Unit.objects.filter(company=company).order_by("name")
    context = {
        "title": "Items & Goods",
        "userProfile": request.userProfile,
        "units": units,
        "default_low_stock": company.default_low_stock_threshold,
    }
    return render(request, "core/items-goods.html", context)


# ═══════════════════════════════════════════════════════════════
#  LIST  (GET)
#  Params: ?search=&unit=&price=&stock=&sort=&order=&page=&per_page=
# ═══════════════════════════════════════════════════════════════

@api_login_required
def item_list_api(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    company = request.company
    base_qs = _get_item_base_qs(company)

    low_thresh = company.default_low_stock_threshold

    # ── Stats (from full dataset, before user filters) ──
    all_items = base_qs.filter(is_active=True)
    stats = all_items.aggregate(
        total=Count("id"),
        low_stock=Count(
            "id",
            filter=Q(
                quantity_in_stock__lte=F("low_stock_threshold")
            ) | Q(
                low_stock_threshold=0,
                quantity_in_stock__lte=low_thresh,
            )
        ),
        out_of_stock=Count("id", filter=Q(quantity_in_stock__lte=0)),
        total_value=Sum(
            F("quantity_in_stock") * F("selling_price"),
        ),
    )

    # Count distinct units used
    unit_count = all_items.values("unit").distinct().count()

    overview = {
        "total_items": stats["total"] or 0,
        "categories": unit_count,
        "low_stock": stats["low_stock"] or 0,
        "out_of_stock": stats["out_of_stock"] or 0,
        "total_value": str(stats["total_value"] or Decimal("0.00")),
    }

    # ── Filters ──
    qs = base_qs

    # Active filter (default: show only active)
    active_filter = request.GET.get("active", "true").strip()
    if active_filter == "true":
        qs = qs.filter(is_active=True)
    elif active_filter == "false":
        qs = qs.filter(is_active=False)
    # else "all" → no filter

    # Search
    search = request.GET.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(description__icontains=search)
        )

    # Unit filter
    unit_filter = request.GET.get("unit", "").strip()
    if unit_filter:
        qs = qs.filter(unit_id=unit_filter)

    # Price range filter (based on selling_price)
    price_filter = request.GET.get("price", "").strip()
    if price_filter:
        if price_filter == "1000+":
            qs = qs.filter(selling_price__gte=1000)
        elif "-" in price_filter:
            parts = price_filter.split("-")
            try:
                p_min, p_max = Decimal(parts[0]), Decimal(parts[1])
                qs = qs.filter(selling_price__gte=p_min, selling_price__lte=p_max)
            except (InvalidOperation, IndexError):
                pass

    # Stock status filter
    stock_filter = request.GET.get("stock", "").strip()
    if stock_filter == "in-stock":
        qs = qs.filter(quantity_in_stock__gt=low_thresh)
    elif stock_filter == "low-stock":
        qs = qs.filter(quantity_in_stock__gt=0, quantity_in_stock__lte=low_thresh)
    elif stock_filter == "out-of-stock":
        qs = qs.filter(quantity_in_stock__lte=0)

    # ── Sort ──
    sort = request.GET.get("sort", "created_at").strip()
    order = request.GET.get("order", "desc").strip()
    prefix = "-" if order == "desc" else ""

    sort_map = {
        "name": "name",
        "created_at": "created_at",
        "selling_price": "selling_price",
        "cost_price": "cost_price",
        "quantity_in_stock": "quantity_in_stock",
        "unit": "unit__short_name",
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
    total_pages = max(1, -(-total // per_page))
    page = min(page, total_pages)
    start = (page - 1) * per_page

    items = qs[start: start + per_page]

    return JsonResponse({
        "success": True,
        "overview": overview,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
        "items": [_serialize_item(i) for i in items],
    })


# ═══════════════════════════════════════════════════════════════
#  CREATE  (POST — multipart/form-data for logo)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def item_create_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data = _parse_multipart(request)
    name = data["name"]

    if not name:
        return JsonResponse({"success": False, "message": "Item name is required."}, status=400)

    company = request.company

    # Check duplicate
    if _get_item_base_qs(company).filter(name__iexact=name).exists():
        return JsonResponse(
            {"success": False, "message": f'Item "{name}" already exists.'},
            status=400,
        )

    # Validate unit
    unit_id = data["unit_id"]
    if not unit_id:
        return JsonResponse({"success": False, "message": "Unit is required."}, status=400)
    try:
        unit = Unit.objects.get(id=unit_id, company=company)
    except Unit.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invalid unit selected."}, status=400)

    item = Item(
        company=company,
        name=name,
        description=data["description"],
        unit=unit,
        cost_price=_safe_decimal(data["cost_price"]),
        selling_price=_safe_decimal(data["selling_price"]),
        quantity_in_stock=0, # Start with 0 stock; can be updated later
        low_stock_threshold=_safe_int(data["low_stock_threshold"]),
        is_active=data["is_active"] != "false",
    )

    logo_file = request.FILES.get("logo")
    if logo_file:
        item.logo = logo_file

    item.save()

    return JsonResponse({
        "success": True,
        "message": f'Item "{name}" added to catalogue.',
        "item": _serialize_item(item),
    }, status=201)


# ═══════════════════════════════════════════════════════════════
#  UPDATE  (POST — multipart/form-data for logo)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def item_update_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data = _parse_multipart(request)
    item_id = data["id"]

    if not item_id:
        return JsonResponse({"success": False, "message": "Item ID is required."}, status=400)

    company = request.company
    try:
        item = _get_item_base_qs(company).get(id=item_id)
    except Item.DoesNotExist:
        return JsonResponse({"success": False, "message": "Item not found."}, status=404)

    name = data["name"]
    if not name:
        return JsonResponse({"success": False, "message": "Item name is required."}, status=400)

    # Check duplicate (exclude self)
    if _get_item_base_qs(company).filter(name__iexact=name).exclude(id=item_id).exists():
        return JsonResponse(
            {"success": False, "message": f'Item "{name}" already exists.'},
            status=400,
        )

    # Validate unit
    unit_id = data["unit_id"]
    if not unit_id:
        return JsonResponse({"success": False, "message": "Unit is required."}, status=400)
    try:
        unit = Unit.objects.get(id=unit_id, company=company)
    except Unit.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invalid unit selected."}, status=400)

    item.name = name
    item.description = data["description"]
    item.unit = unit
    item.cost_price = _safe_decimal(data["cost_price"])
    item.selling_price = _safe_decimal(data["selling_price"])
    item.low_stock_threshold = _safe_int(data["low_stock_threshold"])
    item.is_active = data["is_active"] != "false"

    # Handle logo
    logo_file = request.FILES.get("logo")
    if logo_file:
        if item.logo:
            old_path = os.path.join(settings.MEDIA_ROOT, item.logo.name)
            if os.path.isfile(old_path):
                os.remove(old_path)
        item.logo = logo_file
    elif data["remove_logo"] == "1":
        if item.logo:
            old_path = os.path.join(settings.MEDIA_ROOT, item.logo.name)
            if os.path.isfile(old_path):
                os.remove(old_path)
            item.logo = None

    item.save()

    return JsonResponse({
        "success": True,
        "message": f'Item "{name}" updated successfully.',
        "item": _serialize_item(item),
    })


# ═══════════════════════════════════════════════════════════════
#  DELETE  (POST — JSON body, soft delete: is_active=False)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def item_delete_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    item_ids = data.get("ids", [])
    single_id = data.get("id")
    if single_id and not item_ids:
        item_ids = [single_id]

    if not item_ids:
        return JsonResponse({"success": False, "message": "Item ID(s) required."}, status=400)

    company = request.company
    items = _get_item_base_qs(company).filter(id__in=item_ids, is_active=True)
    count = items.count()

    if count == 0:
        return JsonResponse({"success": False, "message": "No matching items found."}, status=404)

    items.update(
        is_active=False,
        updated_at=timezone.now(),
    )

    label = "item" if count == 1 else "items"
    return JsonResponse({
        "success": True,
        "message": f"{count} {label} deleted successfully.",
        "deleted_ids": list(item_ids),
    })