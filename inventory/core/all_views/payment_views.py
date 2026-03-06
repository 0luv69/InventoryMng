"""
Payment JSON API views.

Endpoints
─────────
GET  /api/payments/list/            → paginated payments + stats + search/filter/sort/tabs
GET  /api/payments/detail/<id>/     → single payment with party & invoice info
POST /api/payments/create/          → create payment + update invoice status + update party balance
POST /api/payments/update/<id>/     → update payment + adjust invoice status + adjust party balance
POST /api/payments/void/<id>/       → soft-void + restore invoice status + restore party balance
POST /api/payments/bulk-void/       → bulk soft-void

Helper endpoints (for form dropdowns)
GET  /api/payments/helpers/customers/       → active customers
GET  /api/payments/helpers/suppliers/       → active suppliers
GET  /api/payments/helpers/users/           → company users
GET  /api/payments/helpers/sale-invoices/   → unpaid/partial sale invoices for a customer
GET  /api/payments/helpers/purchase-invoices/ → unpaid/partial purchase invoices for a supplier
"""

import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, F, Sum
from django.http import JsonResponse
from django.utils import timezone

from ..models import (
    Payment, Party, PurchaseInvoice, SaleInvoice,
    UserProfile, PaymentStatus, PaymentMethod,
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
    """Auto-generate next PAY-XXXX reference number."""
    last = (
        Payment.objects
        .filter(company=company, reference_no__startswith="PAY-")
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
    return f"PAY-{num:04d}"


def _serialize_payment(pay, include_detail=False):
    inv = pay.purchase_invoice or pay.sale_invoice
    data = {
        "id": pay.id,
        "reference_no": pay.reference_no,
        "payment_type": pay.payment_type,
        "party_id": pay.party_id,
        "party_name": pay.party.name,
        "party_type": pay.party.party_type,
        "party_contact": pay.party.contact_person,
        "party_phone": pay.party.phone,
        "party_email": pay.party.email,
        "amount": str(pay.amount),
        "date_paid": pay.date_paid.strftime("%Y-%m-%d") if pay.date_paid else "",
        "received_by_id": pay.received_by_id,
        "received_by_name": (
            pay.received_by.get_full_name() or pay.received_by.username
        ) if pay.received_by else "",
        "payment_method": pay.payment_method,
        "payment_status": pay.payment_status,
        "notes": pay.notes,
        "is_void": pay.is_void,
        "void_reason": pay.void_reason,
        "invoice_ref": inv.reference_no if inv else "",
        "invoice_id": inv.id if inv else None,
        "invoice_type": "purchase" if pay.purchase_invoice else ("sale" if pay.sale_invoice else ""),
        "created_at": pay.created_at.strftime("%Y-%m-%d %H:%M"),
    }
    if include_detail and inv:
        data["invoice_total"] = str(inv.invoice_total)
        data["invoice_paid"] = str(inv.total_paid)
        data["invoice_balance"] = str(inv.balance_due)
        data["invoice_payment_status"] = inv.payment_status
    return data


def _update_linked_invoice(pay):
    """Call update_payment_status on linked invoice."""
    if pay.purchase_invoice:
        pay.purchase_invoice.update_payment_status()
    if pay.sale_invoice:
        pay.sale_invoice.update_payment_status()


def _update_party_balance_on_create(pay):
    """
    Received from customer → decrease their balance (they owe less).
    Sent to supplier → decrease their balance (we owe less), increase total_amount.
    """
    if pay.payment_type == "received":
        pay.party.balance = F("balance") - pay.amount
        pay.party.total_amount = F("total_amount") + pay.amount
        pay.party.save(update_fields=["balance", "total_amount", "updated_at"])
    elif pay.payment_type == "sent":
        pay.party.balance = F("balance") - pay.amount
        pay.party.total_amount = F("total_amount") + pay.amount
        pay.party.save(update_fields=["balance", "total_amount", "updated_at"])


def _reverse_party_balance(pay):
    """Undo the party balance change when voiding / before updating."""
    if pay.payment_type == "received":
        pay.party.balance = F("balance") + pay.amount
        pay.party.total_amount = F("total_amount") - pay.amount
        pay.party.save(update_fields=["balance", "total_amount", "updated_at"])
    elif pay.payment_type == "sent":
        pay.party.balance = F("balance") + pay.amount
        pay.party.total_amount = F("total_amount") - pay.amount
        pay.party.save(update_fields=["balance", "total_amount", "updated_at"])


# ═══════════════════════════════════════════════════════════════
#  HELPER ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@api_login_required
def payment_helpers_customers(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)
    q = request.GET.get("q", "").strip()
    qs = Party.objects.filter(
        company=request.company,
        party_type=Party.PartyType.CUSTOMER,
        is_removed=False, status="active",
    )
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(contact_person__icontains=q)
            | Q(email__icontains=q) | Q(phone__icontains=q)
        )
    return JsonResponse({
        "success": True,
        "customers": [
            {"id": c.id, "name": c.name, "contact_person": c.contact_person,
             "phone": c.phone, "email": c.email, "balance": str(c.balance)}
            for c in qs[:20]
        ],
    })


@api_login_required
def payment_helpers_suppliers(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)
    q = request.GET.get("q", "").strip()
    qs = Party.objects.filter(
        company=request.company,
        party_type=Party.PartyType.SUPPLIER,
        is_removed=False, status="active",
    )
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(contact_person__icontains=q)
            | Q(email__icontains=q) | Q(phone__icontains=q)
        )
    return JsonResponse({
        "success": True,
        "suppliers": [
            {"id": s.id, "name": s.name, "contact_person": s.contact_person,
             "phone": s.phone, "email": s.email, "balance": str(s.balance)}
            for s in qs[:20]
        ],
    })


@api_login_required
def payment_helpers_users(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)
    profiles = UserProfile.objects.filter(
        company=request.company
    ).select_related("user")
    return JsonResponse({
        "success": True,
        "users": [
            {"id": p.user_id, "name": p.user.get_full_name() or p.user.username, "role": p.role}
            for p in profiles
        ],
    })


@api_login_required
def payment_helpers_sale_invoices(request):
    """Sale invoices for a customer (unpaid/partial only for new payments)."""
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)
    customer_id = request.GET.get("customer_id", "").strip()
    if not customer_id:
        return JsonResponse({"success": True, "invoices": []})
    qs = SaleInvoice.objects.filter(
        company=request.company, customer_id=customer_id,
        is_void=False,
        payment_status__in=["unpaid", "partial"],
    ).order_by("-date_dispatched")[:30]
    return JsonResponse({
        "success": True,
        "invoices": [
            {
                "id": inv.id, "reference_no": inv.reference_no,
                "date": inv.date_dispatched.strftime("%Y-%m-%d"),
                "total": str(inv.invoice_total),
                "paid": str(inv.total_paid),
                "balance": str(inv.balance_due),
            }
            for inv in qs
        ],
    })


@api_login_required
def payment_helpers_purchase_invoices(request):
    """Purchase invoices for a supplier (unpaid/partial only)."""
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)
    supplier_id = request.GET.get("supplier_id", "").strip()
    if not supplier_id:
        return JsonResponse({"success": True, "invoices": []})
    qs = PurchaseInvoice.objects.filter(
        company=request.company, supplier_id=supplier_id,
        is_void=False,
        payment_status__in=["unpaid", "partial"],
    ).order_by("-date_received")[:30]
    return JsonResponse({
        "success": True,
        "invoices": [
            {
                "id": inv.id, "reference_no": inv.reference_no,
                "date": inv.date_received.strftime("%Y-%m-%d"),
                "total": str(inv.invoice_total),
                "paid": str(inv.total_paid),
                "balance": str(inv.balance_due),
            }
            for inv in qs
        ],
    })


# ═══════════════════════════════════════════════════════════════
#  LIST  (GET)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def payment_list_api(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)

    company = request.company
    base_qs = Payment.objects.filter(company=company).select_related(
        "party", "received_by", "purchase_invoice", "sale_invoice"
    )

    # ── Stats (exclude voided) ──
    active_qs = base_qs.filter(is_void=False)
    completed_received = active_qs.filter(payment_type="received", payment_status="paid")
    completed_sent = active_qs.filter(payment_type="sent", payment_status="paid")
    total_received = completed_received.aggregate(t=Sum("amount"))["t"] or Decimal("0")
    total_sent = completed_sent.aggregate(t=Sum("amount"))["t"] or Decimal("0")

    now = timezone.now()
    month_start = now.replace(day=1).date()
    this_month_count = active_qs.filter(date_paid__gte=month_start).count()

    overview = {
        "total_received": str(total_received),
        "total_sent": str(total_sent),
        "net_cash_flow": str(total_received - total_sent),
        "this_month": this_month_count,
    }

    # ── Filters ──
    qs = base_qs
    show_void = request.GET.get("show_void", "").strip()
    if show_void != "true":
        qs = qs.filter(is_void=False)

    # Tab filter
    tab = request.GET.get("tab", "all").strip()
    if tab == "in":
        qs = qs.filter(payment_type="received")
    elif tab == "out":
        qs = qs.filter(payment_type="sent")

    search = request.GET.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(reference_no__icontains=search)
            | Q(party__name__icontains=search)
            | Q(notes__icontains=search)
            | Q(purchase_invoice__reference_no__icontains=search)
            | Q(sale_invoice__reference_no__icontains=search)
        ).distinct()

    method = request.GET.get("method", "").strip()
    if method in ("cash", "online", "cheque"):
        qs = qs.filter(payment_method=method)

    status = request.GET.get("status", "").strip()
    if status in ("paid", "partial", "unpaid"):
        qs = qs.filter(payment_status=status)

    date_from = request.GET.get("date_from", "").strip()
    if date_from:
        qs = qs.filter(date_paid__gte=date_from)
    date_to = request.GET.get("date_to", "").strip()
    if date_to:
        qs = qs.filter(date_paid__lte=date_to)

    # ── Sort ──
    sort = request.GET.get("sort", "date_paid").strip()
    order = request.GET.get("order", "desc").strip()
    prefix = "-" if order == "desc" else ""
    sort_map = {
        "date_paid": "date_paid",
        "amount": "amount",
        "reference_no": "reference_no",
        "party": "party__name",
    }
    qs = qs.order_by(
        f"{prefix}{sort_map.get(sort, 'date_paid')}",
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
    payments = qs[start: start + per_page]

    return JsonResponse({
        "success": True,
        "overview": overview,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
        "payments": [_serialize_payment(p) for p in payments],
    })


# ═══════════════════════════════════════════════════════════════
#  DETAIL  (GET)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def payment_detail_api(request, pk):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only."}, status=405)
    try:
        pay = Payment.objects.select_related(
            "party", "received_by", "purchase_invoice", "sale_invoice"
        ).get(id=pk, company=request.company)
    except Payment.DoesNotExist:
        return JsonResponse({"success": False, "message": "Payment not found."}, status=404)
    return JsonResponse({
        "success": True,
        "payment": _serialize_payment(pay, include_detail=True),
    })


# ═══════════════════════════════════════════════════════════════
#  CREATE  (POST)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def payment_create_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company

    # ── Payment type ──
    payment_type = data.get("payment_type", "").strip()
    if payment_type not in ("received", "sent"):
        return JsonResponse({"success": False, "message": "Payment type must be 'received' or 'sent'."}, status=400)

    # ── Party ──
    party_id = data.get("party_id")
    if not party_id:
        return JsonResponse({"success": False, "message": "Party (customer/supplier) is required."}, status=400)

    expected_type = Party.PartyType.CUSTOMER if payment_type == "received" else Party.PartyType.SUPPLIER
    try:
        party = Party.objects.get(id=party_id, company=company, party_type=expected_type, is_removed=False)
    except Party.DoesNotExist:
        label = "Customer" if payment_type == "received" else "Supplier"
        return JsonResponse({"success": False, "message": f"{label} not found."}, status=404)

    # ── Amount ──
    amount = _to_decimal(data.get("amount"), Decimal("0"))
    if amount <= 0:
        return JsonResponse({"success": False, "message": "Amount must be greater than zero."}, status=400)

    # ── Date ──
    date_paid = data.get("date_paid") or timezone.now().date()

    # ── Received by ──
    received_by_id = data.get("received_by_id")
    received_by_user = None
    if received_by_id:
        try:
            profile = UserProfile.objects.select_related("user").get(user_id=received_by_id, company=company)
            received_by_user = profile.user
        except UserProfile.DoesNotExist:
            return JsonResponse({"success": False, "message": "Received-by user not found."}, status=404)

    # ── Method & Status ──
    payment_method = data.get("payment_method", "cash")
    if payment_method not in ("cash", "online", "cheque"):
        payment_method = "cash"

    payment_status = data.get("payment_status", "paid")
    if payment_status not in ("paid", "partial", "unpaid"):
        payment_status = "paid"

    # ── Invoice link (optional) ──
    purchase_invoice = None
    sale_invoice = None
    invoice_id = data.get("invoice_id")
    if invoice_id:
        if payment_type == "received":
            try:
                sale_invoice = SaleInvoice.objects.get(
                    id=invoice_id, company=company, customer=party, is_void=False
                )
            except SaleInvoice.DoesNotExist:
                return JsonResponse({"success": False, "message": "Sale invoice not found."}, status=404)
        elif payment_type == "sent":
            try:
                purchase_invoice = PurchaseInvoice.objects.get(
                    id=invoice_id, company=company, supplier=party, is_void=False
                )
            except PurchaseInvoice.DoesNotExist:
                return JsonResponse({"success": False, "message": "Purchase invoice not found."}, status=404)

    notes = (data.get("notes") or "").strip()

    with transaction.atomic():
        ref_no = _next_reference_no(company)
        pay = Payment.objects.create(
            company=company,
            reference_no=ref_no,
            payment_type=payment_type,
            party=party,
            purchase_invoice=purchase_invoice,
            sale_invoice=sale_invoice,
            amount=amount,
            date_paid=date_paid,
            received_by=received_by_user,
            payment_method=payment_method,
            payment_status=payment_status,
            notes=notes,
        )

        # Update party balance
        _update_party_balance_on_create(pay)

        # Update linked invoice payment status
        _update_linked_invoice(pay)

    pay.refresh_from_db()
    direction_label = "received from" if payment_type == "received" else "sent to"
    return JsonResponse({
        "success": True,
        "message": f"{ref_no} — ${amount} {direction_label} {party.name}.",
        "payment": _serialize_payment(pay, include_detail=True),
    }, status=201)


# ═══════════════════════════════════════════════════════════════
#  UPDATE  (POST)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def payment_update_api(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company
    try:
        pay = Payment.objects.select_related(
            "party", "purchase_invoice", "sale_invoice"
        ).get(id=pk, company=company)
    except Payment.DoesNotExist:
        return JsonResponse({"success": False, "message": "Payment not found."}, status=404)

    if pay.is_void:
        return JsonResponse({"success": False, "message": "Cannot edit a voided payment."}, status=400)

    # ── Payment type ──
    payment_type = data.get("payment_type", "").strip()
    if payment_type not in ("received", "sent"):
        return JsonResponse({"success": False, "message": "Payment type must be 'received' or 'sent'."}, status=400)

    # ── Party ──
    party_id = data.get("party_id")
    if not party_id:
        return JsonResponse({"success": False, "message": "Party is required."}, status=400)
    expected_type = Party.PartyType.CUSTOMER if payment_type == "received" else Party.PartyType.SUPPLIER
    try:
        party = Party.objects.get(id=party_id, company=company, party_type=expected_type, is_removed=False)
    except Party.DoesNotExist:
        label = "Customer" if payment_type == "received" else "Supplier"
        return JsonResponse({"success": False, "message": f"{label} not found."}, status=404)

    # ── Amount ──
    amount = _to_decimal(data.get("amount"), Decimal("0"))
    if amount <= 0:
        return JsonResponse({"success": False, "message": "Amount must be greater than zero."}, status=400)

    # ── Received by ──
    received_by_id = data.get("received_by_id")
    received_by_user = None
    if received_by_id:
        try:
            profile = UserProfile.objects.select_related("user").get(user_id=received_by_id, company=company)
            received_by_user = profile.user
        except UserProfile.DoesNotExist:
            return JsonResponse({"success": False, "message": "Received-by user not found."}, status=404)

    payment_method = data.get("payment_method", "cash")
    if payment_method not in ("cash", "online", "cheque"):
        payment_method = "cash"

    payment_status = data.get("payment_status", "paid")
    if payment_status not in ("paid", "partial", "unpaid"):
        payment_status = "paid"

    # ── Invoice link ──
    purchase_invoice = None
    sale_invoice = None
    invoice_id = data.get("invoice_id")
    if invoice_id:
        if payment_type == "received":
            try:
                sale_invoice = SaleInvoice.objects.get(
                    id=invoice_id, company=company, customer=party, is_void=False
                )
            except SaleInvoice.DoesNotExist:
                return JsonResponse({"success": False, "message": "Sale invoice not found."}, status=404)
        elif payment_type == "sent":
            try:
                purchase_invoice = PurchaseInvoice.objects.get(
                    id=invoice_id, company=company, supplier=party, is_void=False
                )
            except PurchaseInvoice.DoesNotExist:
                return JsonResponse({"success": False, "message": "Purchase invoice not found."}, status=404)

    notes = (data.get("notes") or "").strip()

    with transaction.atomic():
        # ── Reverse old party balance ──
        _reverse_party_balance(pay)

        # ── Remember old invoice to update its status ──
        old_purchase_inv = pay.purchase_invoice
        old_sale_inv = pay.sale_invoice

        # ── Update payment ──
        pay.payment_type = payment_type
        pay.party = party
        pay.amount = amount
        pay.date_paid = data.get("date_paid") or pay.date_paid
        pay.received_by = received_by_user
        pay.payment_method = payment_method
        pay.payment_status = payment_status
        pay.purchase_invoice = purchase_invoice
        pay.sale_invoice = sale_invoice
        pay.notes = notes
        pay.save()

        # ── Apply new party balance ──
        _update_party_balance_on_create(pay)

        # ── Update old invoice status (if changed) ──
        if old_purchase_inv and old_purchase_inv != purchase_invoice:
            old_purchase_inv.update_payment_status()
        if old_sale_inv and old_sale_inv != sale_invoice:
            old_sale_inv.update_payment_status()

        # ── Update new invoice status ──
        _update_linked_invoice(pay)

    pay.refresh_from_db()
    return JsonResponse({
        "success": True,
        "message": f"{pay.reference_no} updated.",
        "payment": _serialize_payment(pay, include_detail=True),
    })


# ═══════════════════════════════════════════════════════════════
#  VOID  (POST)
# ═══════════════════════════════════════════════════════════════

@api_login_required
def payment_void_api(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    company = request.company
    try:
        pay = Payment.objects.select_related(
            "party", "purchase_invoice", "sale_invoice"
        ).get(id=pk, company=company)
    except Payment.DoesNotExist:
        return JsonResponse({"success": False, "message": "Payment not found."}, status=404)

    if pay.is_void:
        return JsonResponse({"success": False, "message": "Payment is already voided."}, status=400)

    void_reason = (data.get("void_reason") or "").strip()
    if not void_reason:
        return JsonResponse({"success": False, "message": "Void reason is required."}, status=400)

    with transaction.atomic():
        # Reverse party balance
        _reverse_party_balance(pay)

        # Void the payment
        pay.is_void = True
        pay.void_reason = void_reason
        pay.save(update_fields=["is_void", "void_reason", "updated_at"])

        # Update linked invoice status
        _update_linked_invoice(pay)

    return JsonResponse({
        "success": True,
        "message": f"{pay.reference_no} voided — party balance restored.",
    })


@api_login_required
def payment_bulk_void_api(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only."}, status=405)

    data, err = _parse_json(request)
    if err:
        return err

    ids = data.get("ids", [])
    void_reason = (data.get("void_reason") or "").strip()
    if not ids:
        return JsonResponse({"success": False, "message": "Payment ID(s) required."}, status=400)
    if not void_reason:
        return JsonResponse({"success": False, "message": "Void reason is required."}, status=400)

    company = request.company
    payments = Payment.objects.filter(
        id__in=ids, company=company, is_void=False
    ).select_related("party", "purchase_invoice", "sale_invoice")

    count = payments.count()
    if count == 0:
        return JsonResponse({"success": False, "message": "No matching payments found."}, status=404)

    with transaction.atomic():
        for pay in payments:
            _reverse_party_balance(pay)
            pay.is_void = True
            pay.void_reason = void_reason
            pay.save(update_fields=["is_void", "void_reason", "updated_at"])
            _update_linked_invoice(pay)

    return JsonResponse({
        "success": True,
        "message": f"{count} payment(s) voided — balances restored.",
        "voided_ids": list(ids),
    })