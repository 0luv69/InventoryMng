"""
Goods-Out (Sale Invoice) JSON API views.

Endpoints
─────────
GET  /api/goodsout/list/          → paginated invoices + stats + search/filter/sort
GET  /api/goodsout/detail/<id>/   → single invoice with line items
POST /api/goodsout/create/        → create invoice + line items + deduct stock
POST /api/goodsout/update/<id>/   → update invoice + line items + adjust stock
POST /api/goodsout/void/<id>/     → soft-void invoice + restore stock
POST /api/goodsout/bulk-void/     → bulk soft-void

Helper endpoints (for form dropdowns)
GET  /api/goodsout/helpers/items/      → active items for this company
GET  /api/goodsout/helpers/customers/  → active customers
GET  /api/goodsout/helpers/users/      → company users
"""

import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, F
from django.http import JsonResponse
from django.utils import timezone

from ..models import (
    SaleInvoice, SaleItem, Party, Item, UserProfile,
    PaymentStatus, DiscountType,
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
    """Auto-generate next SAL-XXXX reference number."""
    last = (
        SaleInvoice.objects
        .filter(company=company, reference_no__startswith="SAL-")
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
    return f"SAL-{num:04d}"


def _calc_line_discount(gross_total, discount_type, discount_amount):
    """Return absolute discount value from type + amount."""
    if discount_type == DiscountType.PERCENTAGE:
        return gross_total * (discount_amount / Decimal("100"))
    return discount_amount   # fixed


def _calc_invoice_discount(subtotal, discount_type, discount_amount):
    """Return absolute invoice-level discount value."""
    if discount_type == DiscountType.PERCENTAGE:
        return subtotal * (discount_amount / Decimal("100"))
    return discount_amount


def _serialize_line(line):
    item = line.item
    return {
        "id": line.id,
        "item_id": item.id,
        "item_name": item.name,
        "item_unit": item.unit.short_name if item.unit else "",
        "quantity": str(line.quantity),
        "selling_price": str(line.selling_price),
        "discount_type": line.discount_type,
        "discount_amount": str(line.discount_amount),
        "gross_total": str(line.gross_total),
        "discount_value": str(line.discount_value),
        "line_total": str(line.line_total),
    }


def _serialize_invoice(inv, include_lines=False):
    data = {
        "id": inv.id,
        "reference_no": inv.reference_no,
        "customer_id": inv.customer_id,
        "customer_name": inv.customer.name,
        "customer_contact": inv.customer.contact_person,
        "date_dispatched": inv.date_dispatched.strftime("%Y-%m-%d") if inv.date_dispatched else "",
        "dispatched_by_id": inv.dispatched_by_id,
        "dispatched_by_name": (
            inv.dispatched_by.get_full_name() or inv.dispatched_by.username
        ) if inv.dispatched_by else "",
        "notes": inv.notes,
        "discount_type": inv.discount_type,
        "discount_amount": str(inv.discount_amount),
        "subtotal": str(inv.subtotal),
        "invoice_discount_value": str(inv.invoice_discount_value),
        "invoice_total": str(inv.invoice_total),
        "payment_status": inv.payment_status,
        "total_paid": str(inv.total_paid),
        "balance_due": str(inv.balance_due),
        "is_void": inv.is_void,
        "void_reason": inv.void_reason,
        "items_count": inv.lines.count(),
        "created_at": inv.created_at.strftime("%Y-%m-%d %H:%M"),
    }
    if include_lines:
        data["lines"] = [
            _serialize_line(l)
            for l in inv.lines.select_related("item", "item__unit").all()
        ]
    return data


def _serialize_invoice_flat(inv):
    """One row per line item — for the flat table view."""
    rows = []
    for line in inv.lines.select_related("item", "item__unit").all():
        rows.append({
            "id": inv.id,
            "line_id": line.id,
            "reference_no": inv.reference_no,
            "customer_id": inv.customer_id,
            "customer_name": inv.customer.name,
            "date_dispatched": inv.date_dispatched.strftime("%Y-%m-%d") if inv.date_dispatched else "",
            "dispatched_by_name": (
                inv.dispatched_by.get_full_name() or inv.dispatched_by.username
            ) if inv.dispatched_by else "",
            "notes": inv.notes,
            "payment_status": inv.payment_status,
            "is_void": inv.is_void,
            "item_id": line.item_id,
            "item_name": line.item.name,
            "item_unit": line.item.unit.short_name if line.item.unit else "",
            "quantity": str(line.quantity),
            "selling_price": str(line.selling_price),
            "discount_type": line.discount_type,
            "discount_amount": str(line.discount_amount),
            "line_total": str(line.line_total),
            "invoice_total": str(inv.invoice_total),
        })
    return rows


# ═══════════════════════════════════════════════════════════════
#  HELPER ENDPOINTS  (dropdowns for the form)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsout_helpers_items(request):
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
                "selling_price": str(i.selling_price),
                "cost_price": str(i.cost_price),
                "stock": str(i.quantity_in_stock),
            }
            for i in items
        ],
    })


@api_login_required
def goodsout_helpers_customers(request):
    """Return active customers for customer dropdown."""
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)

    q = request.GET.get("q", "").strip()
    qs = Party.objects.filter(
        company=request.company,
        party_type=Party.PartyType.CUSTOMER,
        is_removed=False,
        status="active",
    )

    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(contact_person__icontains=q)
            | Q(email__icontains=q)
            | Q(phone__icontains=q)
        )

    customers = qs[:20]
    return JsonResponse({
        "success": True,
        "customers": [
            {
                "id": c.id,
                "name": c.name,
                "contact_person": c.contact_person,
                "phone": c.phone,
                "email": c.email,
            }
            for c in customers
        ],
    })


@api_login_required
def goodsout_helpers_users(request):
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
def goodsout_list_api(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)

    company = request.company
    base_qs = SaleInvoice.objects.filter(company=company).select_related(
        "customer", "dispatched_by"
    ).prefetch_related("lines", "lines__item", "lines__item__unit")

    # ── Stats (before filters, exclude voided) ──
    active_qs = base_qs.filter(is_void=False)
    today = timezone.now().date()
    today_qs = active_qs.filter(date_dispatched=today)

    today_sales = today_qs.count()
    today_units = Decimal("0")
    today_revenue = Decimal("0")
    for inv in today_qs:
        for line in inv.lines.all():
            today_units += line.quantity
        today_revenue += inv.invoice_total

    unpaid_count = active_qs.filter(payment_status="unpaid").count()

    overview = {
        "today_sales": today_sales,
        "units_dispatched_today": str(today_units),
        "revenue_today": str(today_revenue),
        "unpaid_sales": unpaid_count,
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
            | Q(customer__name__icontains=search)
            | Q(notes__icontains=search)
            | Q(lines__item__name__icontains=search)
        ).distinct()

    customer_id = request.GET.get("customer", "").strip()
    if customer_id:
        qs = qs.filter(customer_id=customer_id)

    payment = request.GET.get("payment", "").strip()
    if payment in ("paid", "partial", "unpaid"):
        qs = qs.filter(payment_status=payment)

    date_from = request.GET.get("date_from", "").strip()
    if date_from:
        qs = qs.filter(date_dispatched__gte=date_from)

    date_to = request.GET.get("date_to", "").strip()
    if date_to:
        qs = qs.filter(date_dispatched__lte=date_to)

    # ── Sort ──
    sort = request.GET.get("sort", "date_dispatched").strip()
    order = request.GET.get("order", "desc").strip()
    prefix = "-" if order == "desc" else ""
    sort_map = {
        "date_dispatched": "date_dispatched",
        "reference_no": "reference_no",
        "customer": "customer__name",
        "payment_status": "payment_status",
        "created_at": "created_at",
    }
    qs = qs.order_by(
        f"{prefix}{sort_map.get(sort, 'date_dispatched')}",
        f"{prefix}created_at",
    )

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
    view_mode = request.GET.get("view", "invoice").strip()

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
def goodsout_detail_api(request, pk):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)

    try:
        inv = SaleInvoice.objects.select_related(
            "customer", "dispatched_by"
        ).prefetch_related(
            "lines", "lines__item", "lines__item__unit"
        ).get(id=pk, company=request.company)
    except SaleInvoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)

    return JsonResponse({
        "success": True,
        "invoice": _serialize_invoice(inv, include_lines=True),
    })


# ═══════════════════════════════════════════════════════════════
#  CREATE  (POST)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsout_create_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company

    # ── Validate customer ──
    customer_id = data.get("customer_id")
    if not customer_id:
        return JsonResponse({"success": False, "message": "Customer is required."}, status=400)
    try:
        customer = Party.objects.get(
            id=customer_id, company=company,
            party_type=Party.PartyType.CUSTOMER, is_removed=False,
        )
    except Party.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

    # ── Validate dispatched_by ──
    dispatched_by_id = data.get("dispatched_by_id")
    dispatched_by_user = None
    if dispatched_by_id:
        try:
            profile = UserProfile.objects.select_related("user").get(
                user_id=dispatched_by_id, company=company
            )
            dispatched_by_user = profile.user
        except UserProfile.DoesNotExist:
            return JsonResponse({"success": False, "message": "Dispatched-by user not found."}, status=404)

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

        # Stock check
        if qty > item.quantity_in_stock:
            return JsonResponse({
                "success": False,
                "message": f"Line {idx+1}: Not enough stock for \"{item.name}\" — {item.quantity_in_stock} available, {qty} requested."
            }, status=400)

        sell = _to_decimal(ld.get("selling_price"), Decimal("0"))
        if sell < 0:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Selling price cannot be negative."}, status=400)

        # Line-level discount
        line_disc_type = ld.get("discount_type", "fixed")
        if line_disc_type not in ("fixed", "percentage"):
            line_disc_type = "fixed"
        line_disc_amt = _to_decimal(ld.get("discount_amount"), Decimal("0"))
        if line_disc_amt < 0:
            line_disc_amt = Decimal("0")

        validated_lines.append({
            "item": item,
            "quantity": qty,
            "selling_price": sell,
            "discount_type": line_disc_type,
            "discount_amount": line_disc_amt,
        })

    # ── Invoice-level discount ──
    inv_disc_type = data.get("discount_type", "fixed")
    if inv_disc_type not in ("fixed", "percentage"):
        inv_disc_type = "fixed"
    inv_disc_amt = _to_decimal(data.get("discount_amount"), Decimal("0"))
    if inv_disc_amt < 0:
        inv_disc_amt = Decimal("0")

    # ── Create in a transaction ──
    with transaction.atomic():
        ref_no = _next_reference_no(company)

        invoice = SaleInvoice.objects.create(
            company=company,
            reference_no=ref_no,
            customer=customer,
            date_dispatched=data.get("date_dispatched") or timezone.now().date(),
            dispatched_by=dispatched_by_user,
            notes=(data.get("notes") or "").strip(),
            discount_type=inv_disc_type,
            discount_amount=inv_disc_amt,
            payment_status=PaymentStatus.UNPAID,
        )

        for ld in validated_lines:
            SaleItem.objects.create(
                invoice=invoice,
                item=ld["item"],
                quantity=ld["quantity"],
                selling_price=ld["selling_price"],
                discount_type=ld["discount_type"],
                discount_amount=ld["discount_amount"],
            )
            # Deduct stock
            ld["item"].quantity_in_stock = F("quantity_in_stock") - ld["quantity"]
            ld["item"].save(update_fields=["quantity_in_stock", "updated_at"])

        # Update customer balance (they owe us)
        customer.balance = F("balance") + invoice.invoice_total
        customer.save(update_fields=["balance", "updated_at"])

    invoice.refresh_from_db()
    return JsonResponse({
        "success": True,
        "message": f"Sale {ref_no} created — {len(validated_lines)} item(s) dispatched, stock updated.",
        "invoice": _serialize_invoice(invoice, include_lines=True),
    }, status=201)


# ═══════════════════════════════════════════════════════════════
#  UPDATE  (POST)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsout_update_api(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company

    try:
        invoice = SaleInvoice.objects.select_related("customer").prefetch_related(
            "lines", "lines__item"
        ).get(id=pk, company=company)
    except SaleInvoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)

    if invoice.is_void:
        return JsonResponse({"success": False, "message": "Cannot edit a voided invoice."}, status=400)

    # ── Validate customer ──
    customer_id = data.get("customer_id")
    if not customer_id:
        return JsonResponse({"success": False, "message": "Customer is required."}, status=400)
    try:
        customer = Party.objects.get(
            id=customer_id, company=company,
            party_type=Party.PartyType.CUSTOMER, is_removed=False,
        )
    except Party.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

    # ── Validate dispatched_by ──
    dispatched_by_id = data.get("dispatched_by_id")
    dispatched_by_user = None
    if dispatched_by_id:
        try:
            profile = UserProfile.objects.select_related("user").get(
                user_id=dispatched_by_id, company=company
            )
            dispatched_by_user = profile.user
        except UserProfile.DoesNotExist:
            return JsonResponse({"success": False, "message": "Dispatched-by user not found."}, status=404)

    # ── Validate lines ──
    lines_data = data.get("lines", [])
    if not lines_data or not isinstance(lines_data, list):
        return JsonResponse({"success": False, "message": "At least one item is required."}, status=400)

    # Build a map of old quantities per item so we can calculate net stock change
    old_qty_map = {}
    for old_line in invoice.lines.select_related("item").all():
        old_qty_map[old_line.item_id] = old_qty_map.get(old_line.item_id, Decimal("0")) + old_line.quantity

    validated_lines = []
    new_qty_map = {}
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

        # Accumulate new qty for this item
        new_qty_map[item.id] = new_qty_map.get(item.id, Decimal("0")) + qty

        sell = _to_decimal(ld.get("selling_price"), Decimal("0"))
        if sell < 0:
            return JsonResponse({"success": False, "message": f"Line {idx+1}: Selling price cannot be negative."}, status=400)

        line_disc_type = ld.get("discount_type", "fixed")
        if line_disc_type not in ("fixed", "percentage"):
            line_disc_type = "fixed"
        line_disc_amt = _to_decimal(ld.get("discount_amount"), Decimal("0"))
        if line_disc_amt < 0:
            line_disc_amt = Decimal("0")

        validated_lines.append({
            "item": item,
            "quantity": qty,
            "selling_price": sell,
            "discount_type": line_disc_type,
            "discount_amount": line_disc_amt,
        })

    # Stock availability check (considering restored old stock)
    all_item_ids = set(list(old_qty_map.keys()) + list(new_qty_map.keys()))
    for item_id in all_item_ids:
        old_q = old_qty_map.get(item_id, Decimal("0"))
        new_q = new_qty_map.get(item_id, Decimal("0"))
        net_change = new_q - old_q  # positive = need more stock
        if net_change > 0:
            item_obj = Item.objects.get(id=item_id, company=company)
            if net_change > item_obj.quantity_in_stock:
                return JsonResponse({
                    "success": False,
                    "message": f"Not enough stock for \"{item_obj.name}\" — {item_obj.quantity_in_stock} available, need {net_change} more."
                }, status=400)

    # ── Invoice-level discount ──
    inv_disc_type = data.get("discount_type", "fixed")
    if inv_disc_type not in ("fixed", "percentage"):
        inv_disc_type = "fixed"
    inv_disc_amt = _to_decimal(data.get("discount_amount"), Decimal("0"))
    if inv_disc_amt < 0:
        inv_disc_amt = Decimal("0")

    with transaction.atomic():
        # ── Reverse old stock ──
        old_total = invoice.invoice_total
        old_customer = invoice.customer

        for old_line in invoice.lines.select_related("item").all():
            old_line.item.quantity_in_stock = F("quantity_in_stock") + old_line.quantity
            old_line.item.save(update_fields=["quantity_in_stock", "updated_at"])

        # Reverse old customer balance
        old_customer.balance = F("balance") - old_total
        old_customer.save(update_fields=["balance", "updated_at"])

        # ── Delete old lines ──
        invoice.lines.all().delete()

        # ── Update header ──
        invoice.customer = customer
        invoice.date_dispatched = data.get("date_dispatched") or invoice.date_dispatched
        invoice.dispatched_by = dispatched_by_user
        invoice.notes = (data.get("notes") or "").strip()
        invoice.discount_type = inv_disc_type
        invoice.discount_amount = inv_disc_amt
        invoice.save()

        # ── Create new lines + deduct stock ──
        for ld in validated_lines:
            SaleItem.objects.create(
                invoice=invoice,
                item=ld["item"],
                quantity=ld["quantity"],
                selling_price=ld["selling_price"],
                discount_type=ld["discount_type"],
                discount_amount=ld["discount_amount"],
            )
            ld["item"].quantity_in_stock = F("quantity_in_stock") - ld["quantity"]
            ld["item"].save(update_fields=["quantity_in_stock", "updated_at"])

        # Update customer balance
        customer.refresh_from_db()
        customer.balance = F("balance") + invoice.invoice_total
        customer.save(update_fields=["balance", "updated_at"])

    invoice.refresh_from_db()
    return JsonResponse({
        "success": True,
        "message": f"Sale {invoice.reference_no} updated — stock adjusted.",
        "invoice": _serialize_invoice(invoice, include_lines=True),
    })


# ═══════════════════════════════════════════════════════════════
#  VOID  (POST)  — soft delete + restore stock
# ═══════════════════════════════════════════════════════════════

@api_login_required
def goodsout_void_api(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company
    try:
        invoice = SaleInvoice.objects.select_related("customer").prefetch_related(
            "lines", "lines__item"
        ).get(id=pk, company=company)
    except SaleInvoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)

    if invoice.is_void:
        return JsonResponse({"success": False, "message": "Invoice is already voided."}, status=400)

    void_reason = (data.get("void_reason") or "").strip()
    if not void_reason:
        return JsonResponse({"success": False, "message": "Void reason is required."}, status=400)

    with transaction.atomic():
        # Restore stock
        for line in invoice.lines.select_related("item").all():
            line.item.quantity_in_stock = F("quantity_in_stock") + line.quantity
            line.item.save(update_fields=["quantity_in_stock", "updated_at"])

        # Reverse customer balance
        inv_total = invoice.invoice_total
        invoice.customer.balance = F("balance") - inv_total
        invoice.customer.save(update_fields=["balance", "updated_at"])

        invoice.is_void = True
        invoice.void_reason = void_reason
        invoice.save(update_fields=["is_void", "void_reason", "updated_at"])

    return JsonResponse({
        "success": True,
        "message": f"Sale {invoice.reference_no} voided — stock restored.",
    })


@api_login_required
def goodsout_bulk_void_api(request):
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
    invoices = SaleInvoice.objects.filter(
        id__in=ids, company=company, is_void=False
    ).select_related("customer").prefetch_related("lines", "lines__item")

    count = invoices.count()
    if count == 0:
        return JsonResponse({"success": False, "message": "No matching invoices found."}, status=404)

    with transaction.atomic():
        for inv in invoices:
            for line in inv.lines.select_related("item").all():
                line.item.quantity_in_stock = F("quantity_in_stock") + line.quantity
                line.item.save(update_fields=["quantity_in_stock", "updated_at"])

            inv_total = inv.invoice_total
            inv.customer.balance = F("balance") - inv_total
            inv.customer.save(update_fields=["balance", "updated_at"])

            inv.is_void = True
            inv.void_reason = void_reason
            inv.save(update_fields=["is_void", "void_reason", "updated_at"])

    return JsonResponse({
        "success": True,
        "message": f"{count} sale(s) voided — stock restored.",
        "voided_ids": list(ids),
    })