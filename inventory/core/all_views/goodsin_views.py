"""
Goods-In (Purchase Invoice) JSON API views.

Endpoints
─────────
GET  /api/goodsin/list/          → paginated invoices + stats + search/filter/sort
GET  /api/goodsin/detail/<id>/   → single invoice with line items
POST /api/goodsin/create/        → create invoice + line items + update stock
POST /api/goodsin/update/<id>/   → update invoice + line items + adjust stock
POST /api/goodsin/void/<id>/     → soft-void invoice + reverse stock
POST /api/goodsin/bulk-void/     → bulk soft-void

Helper endpoints (for form dropdowns)
GET  /api/goodsin/helpers/items/      → active items for this company
GET  /api/goodsin/helpers/suppliers/  → active suppliers
GET  /api/goodsin/helpers/users/      → company users
"""

import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum, Count, F, Value, CharField
from django.db.models.functions import Concat
from django.http import JsonResponse
from django.utils import timezone

from ..models import (
    PurchaseInvoice, PurchaseItem, Party, Item, UserProfile,
    PaymentStatus,
)
from ..decorators import api_login_required


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _parse_json(request):
    try:
        return json.loads(request.body.decode("utf-8")), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse(
            {"success": False, "message": "Invalid JSON."}, status=400
        )


def _to_decimal(val, default=Decimal("0")):
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _next_reference_no(company):
    """Auto-generate next PUR-XXXX reference number."""
    last = (
        PurchaseInvoice.objects
        .filter(company=company, reference_no__startswith="PUR-")
        .order_by("-id")
        .values_list("reference_no", flat=True)
        .first()
    )
    if last:
        try:
            num = int(last.split("-")[1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"PUR-{num:04d}"


def _serialize_line(line):
    item = line.item
    return {
        "id": line.id,
        "item_id": item.id,
        "item_name": item.name,
        "item_unit": item.unit.short_name if item.unit else "",
        "quantity": str(line.quantity),
        "cost_price": str(line.cost_price),
        "selling_price": str(line.selling_price) if line.selling_price is not None else "",
        "line_total": str(line.line_total),
    }


def _serialize_invoice(inv, include_lines=False):
    data = {
        "id": inv.id,
        "reference_no": inv.reference_no,
        "supplier_id": inv.supplier_id,
        "supplier_name": inv.supplier.name,
        "date_received": inv.date_received.strftime("%Y-%m-%d") if inv.date_received else "",
        "received_by_id": inv.received_by_id,
        "received_by_name": (
            inv.received_by.get_full_name() or inv.received_by.username
        ) if inv.received_by else "",
        "notes": inv.notes,
        "payment_status": inv.payment_status,
        "is_void": inv.is_void,
        "void_reason": inv.void_reason,
        "invoice_total": str(inv.invoice_total),
        "total_paid": str(inv.total_paid),
        "balance_due": str(inv.balance_due),
        "items_count": inv.lines.count(),
        "created_at": inv.created_at.strftime("%Y-%m-%d %H:%M"),
    }
    if include_lines:
        data["lines"] = [_serialize_line(l) for l in inv.lines.select_related("item", "item__unit").all()]
    return data


def _serialize_invoice_flat(inv):
    """One row per line item — for the flat table view."""
    rows = []
    for line in inv.lines.select_related("item", "item__unit").all():
        rows.append({
            "id": inv.id,
            "line_id": line.id,
            "reference_no": inv.reference_no,
            "supplier_id": inv.supplier_id,
            "supplier_name": inv.supplier.name,
            "date_received": inv.date_received.strftime("%Y-%m-%d") if inv.date_received else "",
            "received_by_name": (
                inv.received_by.get_full_name() or inv.received_by.username
            ) if inv.received_by else "",
            "notes": inv.notes,
            "payment_status": inv.payment_status,
            "is_void": inv.is_void,
            "item_id": line.item_id,
            "item_name": line.item.name,
            "item_unit": line.item.unit.short_name if line.item.unit else "",
            "quantity": str(line.quantity),
            "cost_price": str(line.cost_price),
            "selling_price": str(line.selling_price) if line.selling_price is not None else "",
            "line_total": str(line.line_total),
            "invoice_total": str(inv.invoice_total),
        })
    return rows


# ═══════════════════════════════════════════════════════════════
#  HELPER ENDPOINTS  (dropdowns for the form)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsin_helpers_items(request):
    """Return active items for item search dropdown."""
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)

    q = request.GET.get("q", "").strip()
    qs = Item.objects.filter(
        company=request.company, is_active=True
    ).select_related("unit")

    if q:
        qs = qs.filter(name__icontains=q)

    items = qs[:20]
    return JsonResponse({
        "success": True,
        "items": [
            {
                "id": i.id,
                "name": i.name,
                "unit": i.unit.short_name if i.unit else "",
                "cost_price": str(i.cost_price),
                "selling_price": str(i.selling_price),
                "stock": str(i.quantity_in_stock),
            }
            for i in items
        ],
    })


@api_login_required
def goodsin_helpers_suppliers(request):
    """Return active suppliers for supplier dropdown."""
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)

    q = request.GET.get("q", "").strip()
    qs = Party.objects.filter(
        company=request.company,
        party_type=Party.PartyType.SUPPLIER,
        is_removed=False,
        status="active",
    )

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(contact_person__icontains=q))

    suppliers = qs[:20]
    return JsonResponse({
        "success": True,
        "suppliers": [
            {
                "id": s.id,
                "name": s.name,
                "contact_person": s.contact_person,
                "phone": s.phone,
            }
            for s in suppliers
        ],
    })


@api_login_required
def goodsin_helpers_users(request):
    """Return all users in the same company."""
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)

    profiles = UserProfile.objects.filter(
        company=request.company
    ).select_related("user")

    return JsonResponse({
        "success": True,
        "users": [
            {
                "id": p.user_id,
                "name": p.user.get_full_name() or p.user.username,
                "role": p.role,
            }
            for p in profiles
        ],
    })


# ═══════════════════════════════════════════════════════════════
#  LIST  (GET)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsin_list_api(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)

    company = request.company
    base_qs = PurchaseInvoice.objects.filter(company=company).select_related(
        "supplier", "received_by"
    ).prefetch_related("lines", "lines__item", "lines__item__unit")

    # ── Stats (before filters, exclude voided) ──
    active_qs = base_qs.filter(is_void=False)
    today = timezone.now().date()
    today_qs = active_qs.filter(date_received=today)

    today_invoices = today_qs.count()
    today_units = 0
    today_cost = Decimal("0")
    for inv in today_qs:
        for line in inv.lines.all():
            today_units += line.quantity
            today_cost += line.line_total

    unpaid_count = active_qs.filter(payment_status="unpaid").count()

    overview = {
        "today_receipts": today_invoices,
        "units_received_today": str(today_units),
        "total_cost_today": str(today_cost),
        "unpaid_receipts": unpaid_count,
    }

    # ── Filters ──
    qs = base_qs
    show_void = request.GET.get("show_void", "").strip()
    if show_void != "true":
        qs = qs.filter(is_void=False)

    search = request.GET.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(reference_no__icontains=search)
            | Q(supplier__name__icontains=search)
            | Q(notes__icontains=search)
            | Q(lines__item__name__icontains=search)
        ).distinct()

    supplier_id = request.GET.get("supplier", "").strip()
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)

    payment = request.GET.get("payment", "").strip()
    if payment in ("paid", "partial", "unpaid"):
        qs = qs.filter(payment_status=payment)

    date_from = request.GET.get("date_from", "").strip()
    if date_from:
        qs = qs.filter(date_received__gte=date_from)

    date_to = request.GET.get("date_to", "").strip()
    if date_to:
        qs = qs.filter(date_received__lte=date_to)

    # ── Sort ──
    sort = request.GET.get("sort", "date_received").strip()
    order = request.GET.get("order", "desc").strip()
    prefix = "-" if order == "desc" else ""
    sort_map = {
        "date_received": "date_received",
        "reference_no": "reference_no",
        "supplier": "supplier__name",
        "payment_status": "payment_status",
        "created_at": "created_at",
    }
    qs = qs.order_by(f"{prefix}{sort_map.get(sort, 'date_received')}", f"{prefix}created_at")

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
    invoices = qs[start: start + per_page]

    # ── View mode ──
    view_mode = request.GET.get("view", "invoice").strip()  # "invoice" or "flat"

    if view_mode == "flat":
        rows = []
        for inv in invoices:
            rows.extend(_serialize_invoice_flat(inv))
        data_key = "rows"
        data_val = rows
    else:
        data_key = "invoices"
        data_val = [_serialize_invoice(inv, include_lines=True) for inv in invoices]

    return JsonResponse({
        "success": True,
        "overview": overview,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
        data_key: data_val,
    })


# ═══════════════════════════════════════════════════════════════
#  DETAIL  (GET)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsin_detail_api(request, pk):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)

    try:
        inv = PurchaseInvoice.objects.select_related(
            "supplier", "received_by"
        ).prefetch_related(
            "lines", "lines__item", "lines__item__unit"
        ).get(id=pk, company=request.company)
    except PurchaseInvoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)

    return JsonResponse({
        "success": True,
        "invoice": _serialize_invoice(inv, include_lines=True),
    })


# ═══════════════════════════════════════════════════════════════
#  CREATE  (POST)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsin_create_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company

    # ── Validate supplier ──
    supplier_id = data.get("supplier_id")
    if not supplier_id:
        return JsonResponse({"success": False, "message": "Supplier is required."}, status=400)
    try:
        supplier = Party.objects.get(
            id=supplier_id, company=company,
            party_type=Party.PartyType.SUPPLIER, is_removed=False,
        )
    except Party.DoesNotExist:
        return JsonResponse({"success": False, "message": "Supplier not found."}, status=404)

    # ── Validate received_by ──
    received_by_id = data.get("received_by_id")
    received_by_user = None
    if received_by_id:
        try:
            profile = UserProfile.objects.select_related("user").get(
                user_id=received_by_id, company=company
            )
            received_by_user = profile.user
        except UserProfile.DoesNotExist:
            return JsonResponse({"success": False, "message": "Received-by user not found."}, status=404)

    # ── Validate line items ──
    lines_data = data.get("lines", [])
    if not lines_data or not isinstance(lines_data, list):
        return JsonResponse({"success": False, "message": "At least one item is required."}, status=400)

    validated_lines = []
    for idx, ld in enumerate(lines_data):
        item_id = ld.get("item_id")
        if not item_id:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Item is required."}, status=400)
        try:
            item = Item.objects.get(id=item_id, company=company, is_active=True)
        except Item.DoesNotExist:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Item not found."}, status=404)

        qty = _to_decimal(ld.get("quantity"), Decimal("0"))
        if qty <= 0:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Quantity must be > 0."}, status=400)

        cost = _to_decimal(ld.get("cost_price"), Decimal("0"))
        if cost < 0:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Cost price cannot be negative."}, status=400)

        sell_raw = ld.get("selling_price")
        sell = _to_decimal(sell_raw, None) if sell_raw not in (None, "", "null") else None

        validated_lines.append({
            "item": item,
            "quantity": qty,
            "cost_price": cost,
            "selling_price": sell,
        })

    # ── Create in a transaction ──
    with transaction.atomic():
        ref_no = _next_reference_no(company)

        invoice = PurchaseInvoice.objects.create(
            company=company,
            reference_no=ref_no,
            supplier=supplier,
            date_received=data.get("date_received") or timezone.now().date(),
            received_by=received_by_user,
            notes=(data.get("notes") or "").strip(),
            payment_status=PaymentStatus.UNPAID,
        )

        for ld in validated_lines:
            PurchaseItem.objects.create(
                invoice=invoice,
                item=ld["item"],
                quantity=ld["quantity"],
                cost_price=ld["cost_price"],
                selling_price=ld["selling_price"],
            )
            # Update stock
            ld["item"].quantity_in_stock = F("quantity_in_stock") + ld["quantity"]
            ld["item"].save(update_fields=["quantity_in_stock", "updated_at"])

            # Update item cost_price from this batch
            ld["item"].refresh_from_db()
            ld["item"].cost_price = ld["cost_price"]
            if ld["selling_price"] is not None:
                ld["item"].selling_price = ld["selling_price"]
            ld["item"].save(update_fields=["cost_price", "selling_price", "updated_at"])

        # Update supplier balance (they owe us nothing, we owe them)
        supplier.balance = F("balance") + invoice.invoice_total
        supplier.save(update_fields=["balance", "updated_at"])

    invoice.refresh_from_db()
    return JsonResponse({
        "success": True,
        "message": f"Invoice {ref_no} created — {len(validated_lines)} item(s) received, stock updated.",
        "invoice": _serialize_invoice(invoice, include_lines=True),
    }, status=201)


# ═══════════════════════════════════════════════════════════════
#  UPDATE  (POST)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsin_update_api(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company

    try:
        invoice = PurchaseInvoice.objects.select_related("supplier").prefetch_related(
            "lines", "lines__item"
        ).get(id=pk, company=company)
    except PurchaseInvoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)

    if invoice.is_void:
        return JsonResponse({"success": False, "message": "Cannot edit a voided invoice."}, status=400)

    # ── Validate supplier ──
    supplier_id = data.get("supplier_id")
    if not supplier_id:
        return JsonResponse({"success": False, "message": "Supplier is required."}, status=400)
    try:
        supplier = Party.objects.get(
            id=supplier_id, company=company,
            party_type=Party.PartyType.SUPPLIER, is_removed=False,
        )
    except Party.DoesNotExist:
        return JsonResponse({"success": False, "message": "Supplier not found."}, status=404)

    # ── Validate received_by ──
    received_by_id = data.get("received_by_id")
    received_by_user = None
    if received_by_id:
        try:
            profile = UserProfile.objects.select_related("user").get(
                user_id=received_by_id, company=company
            )
            received_by_user = profile.user
        except UserProfile.DoesNotExist:
            return JsonResponse({"success": False, "message": "Received-by user not found."}, status=404)

    # ── Validate lines ──
    lines_data = data.get("lines", [])
    if not lines_data or not isinstance(lines_data, list):
        return JsonResponse({"success": False, "message": "At least one item is required."}, status=400)

    validated_lines = []
    for idx, ld in enumerate(lines_data):
        item_id = ld.get("item_id")
        if not item_id:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Item is required."}, status=400)
        try:
            item = Item.objects.get(id=item_id, company=company, is_active=True)
        except Item.DoesNotExist:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Item not found."}, status=404)

        qty = _to_decimal(ld.get("quantity"), Decimal("0"))
        if qty <= 0:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Quantity must be > 0."}, status=400)

        cost = _to_decimal(ld.get("cost_price"), Decimal("0"))
        if cost < 0:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Cost price cannot be negative."}, status=400)

        sell_raw = ld.get("selling_price")
        sell = _to_decimal(sell_raw, None) if sell_raw not in (None, "", "null") else None

        validated_lines.append({
            "item": item,
            "quantity": qty,
            "cost_price": cost,
            "selling_price": sell,
        })

    with transaction.atomic():
        # ── Reverse old stock ──
        old_total = invoice.invoice_total
        old_supplier = invoice.supplier

        for old_line in invoice.lines.select_related("item").all():
            old_line.item.quantity_in_stock = F("quantity_in_stock") - old_line.quantity
            old_line.item.save(update_fields=["quantity_in_stock", "updated_at"])

        # Reverse old supplier balance
        old_supplier.balance = F("balance") - old_total
        old_supplier.save(update_fields=["balance", "updated_at"])

        # ── Delete old lines ──
        invoice.lines.all().delete()

        # ── Update header ──
        invoice.supplier = supplier
        invoice.date_received = data.get("date_received") or invoice.date_received
        invoice.received_by = received_by_user
        invoice.notes = (data.get("notes") or "").strip()
        invoice.save()

        # ── Create new lines + update stock ──
        for ld in validated_lines:
            PurchaseItem.objects.create(
                invoice=invoice,
                item=ld["item"],
                quantity=ld["quantity"],
                cost_price=ld["cost_price"],
                selling_price=ld["selling_price"],
            )
            ld["item"].quantity_in_stock = F("quantity_in_stock") + ld["quantity"]
            ld["item"].save(update_fields=["quantity_in_stock", "updated_at"])

            ld["item"].refresh_from_db()
            ld["item"].cost_price = ld["cost_price"]
            if ld["selling_price"] is not None:
                ld["item"].selling_price = ld["selling_price"]
            ld["item"].save(update_fields=["cost_price", "selling_price", "updated_at"])

        # Update supplier balance
        supplier.refresh_from_db()
        supplier.balance = F("balance") + invoice.invoice_total
        supplier.save(update_fields=["balance", "updated_at"])

    invoice.refresh_from_db()
    return JsonResponse({
        "success": True,
        "message": f"Invoice {invoice.reference_no} updated — stock adjusted.",
        "invoice": _serialize_invoice(invoice, include_lines=True),
    })


# ═══════════════════════════════════════════════════════════════
#  VOID  (POST)  — soft delete + reverse stock
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsin_void_api(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company
    try:
        invoice = PurchaseInvoice.objects.select_related("supplier").prefetch_related(
            "lines", "lines__item"
        ).get(id=pk, company=company)
    except PurchaseInvoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)

    if invoice.is_void:
        return JsonResponse({"success": False, "message": "Invoice is already voided."}, status=400)

    void_reason = (data.get("void_reason") or "").strip()
    if not void_reason:
        return JsonResponse({"success": False, "message": "Void reason is required."}, status=400)

    with transaction.atomic():
        # Reverse stock
        for line in invoice.lines.select_related("item").all():
            line.item.quantity_in_stock = F("quantity_in_stock") - line.quantity
            line.item.save(update_fields=["quantity_in_stock", "updated_at"])

        # Reverse supplier balance
        inv_total = invoice.invoice_total
        invoice.supplier.balance = F("balance") - inv_total
        invoice.supplier.save(update_fields=["balance", "updated_at"])

        invoice.is_void = True
        invoice.void_reason = void_reason
        invoice.save(update_fields=["is_void", "void_reason", "updated_at"])

    return JsonResponse({
        "success": True,
        "message": f"Invoice {invoice.reference_no} voided — stock reversed.",
    })


@api_login_required
def goodsin_bulk_void_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    ids = data.get("ids", [])
    void_reason = (data.get("void_reason") or "").strip()
    if not ids:
        return JsonResponse({"success": False, "message": "Invoice ID(s) required."}, status=400)
    if not void_reason:
        return JsonResponse({"success": False, "message": "Void reason is required."}, status=400)

    company = request.company
    invoices = PurchaseInvoice.objects.filter(
        id__in=ids, company=company, is_void=False
    ).select_related("supplier").prefetch_related("lines", "lines__item")

    count = invoices.count()
    if count == 0:
        return JsonResponse({"success": False, "message": "No matching invoices found."}, status=404)

    with transaction.atomic():
        for inv in invoices:
            for line in inv.lines.select_related("item").all():
                line.item.quantity_in_stock = F("quantity_in_stock") - line.quantity
                line.item.save(update_fields=["quantity_in_stock", "updated_at"])

            inv_total = inv.invoice_total
            inv.supplier.balance = F("balance") - inv_total
            inv.supplier.save(update_fields=["balance", "updated_at"])

            inv.is_void = True
            inv.void_reason = void_reason
            inv.save(update_fields=["is_void", "void_reason", "updated_at"])

    return JsonResponse({
        "success": True,
        "message": f"{count} invoice(s) voided — stock reversed.",
        "voided_ids": list(ids),
    })