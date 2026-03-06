from decimal import Decimal

from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html

from .models import (
    Company,
    Item,
    Party,
    Payment,
    PurchaseInvoice,
    PurchaseItem,
    RequestDemo,
    SaleInvoice,
    SaleItem,
    SpoilageLoss,
    Unit,
    UserProfile,
    UserSession,
)


# ═══════════════════════════════════════════════════════════════
#  HELPERS  – reusable badge / color formatters
# ═══════════════════════════════════════════════════════════════

PAYMENT_STATUS_COLORS = {
    "paid": "#16a34a",      # green
    "partial": "#d97706",   # amber
    "unpaid": "#dc2626",    # red
}

PARTY_STATUS_COLORS = {
    "active": "#16a34a",
    "inactive": "#9ca3af",
}


def _badge(text, color, bg=None):
    """Render a small colored pill badge."""
    bg = bg or f"{color}18"     # 18 = ~10% opacity hex suffix
    return format_html(
        '<span style="background:{}; color:{}; padding:2px 8px; '
        'border-radius:12px; font-size:11px; font-weight:600;">{}</span>',
        bg, color, text,
    )


def _currency(amount):
    """Format a decimal nicely."""
    if amount is None:
        return "–"
    return f"{amount:,.2f}"


# ═══════════════════════════════════════════════════════════════
#  COMPANY
# ═══════════════════════════════════════════════════════════════

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = (
        "name", "slug", "phone", "email", "currency",
        "default_low_stock_threshold", "fiscal_year_start_month",
        "created_at",
    )
    search_fields = ("name", "slug", "phone", "email", "city", "state", "country")
    list_filter = ("currency", "country", "created_at")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)
    list_per_page = 25

    fieldsets = (
        ("Identity", {
            "fields": ("name", "slug", "logo"),
        }),
        ("Contact Information", {
            "fields": ("phone", "email", "address", "city", "state", "country"),
        }),
        ("Financial", {
            "fields": ("currency", "tax_id"),
        }),
        ("Settings", {
            "fields": ("default_low_stock_threshold", "fiscal_year_start_month"),
        }),
    )


# ═══════════════════════════════════════════════════════════════
#  USER PROFILE
# ═══════════════════════════════════════════════════════════════

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user", "get_full_name", "company", "role_badge", "is_owner", "phone_num", "created_at",
    )
    search_fields = (
        "user__username", "user__email", "user__first_name",
        "user__last_name", "company__name", "phone_num",
    )
    list_filter = ("role", "is_owner", "company", "created_at")
    autocomplete_fields = ("user", "company")
    ordering = ("company__name", "user__username")
    list_per_page = 25

    fieldsets = (
        (None, {
            "fields": ("user", "company", "phone_num"),
        }),
        ("Role & Permissions", {
            "fields": ("role", "is_owner"),
        }),
    )

    @admin.display(description="Full Name")
    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    @admin.display(description="Role")
    def role_badge(self, obj):
        colors = {
            "owner": "#7c3aed",     # purple
            "admin": "#2563eb",     # blue
            "staff": "#6b7280",     # gray
        }
        color = colors.get(obj.role, "#6b7280")
        return _badge(obj.get_role_display(), color)


# ═══════════════════════════════════════════════════════════════
#  USER SESSION
# ═══════════════════════════════════════════════════════════════

@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = (
        "user", "session_key", "ip_address", "short_uuid",
        "last_activity", "created_at",
    )
    search_fields = ("user__username", "user__email", "ip_address", "session_key")
    list_filter = ("last_activity", "created_at")
    autocomplete_fields = ("user",)
    ordering = ("-last_activity",)
    list_per_page = 30
    readonly_fields = ("uuid", "created_at", "last_activity")

    @admin.display(description="UUID")
    def short_uuid(self, obj):
        """Show first 8 chars of UUID for readability."""
        return str(obj.uuid)[:8] + "…"


# ═══════════════════════════════════════════════════════════════
#  REQUEST DEMO
# ═══════════════════════════════════════════════════════════════

@admin.register(RequestDemo)
class RequestDemoAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "short_message", "created_at")
    search_fields = ("name", "email", "phone")
    list_filter = ("created_at",)
    ordering = ("-created_at",)
    list_per_page = 25
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Message")
    def short_message(self, obj):
        if obj.message and len(obj.message) > 60:
            return obj.message[:60] + "…"
        return obj.message or "–"


# ═══════════════════════════════════════════════════════════════
#  UNIT
# ═══════════════════════════════════════════════════════════════

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "company", "created_at")
    search_fields = ("name", "short_name", "company__name")
    list_filter = ("company",)
    autocomplete_fields = ("company",)
    ordering = ("company__name", "name")
    list_per_page = 30


# ═══════════════════════════════════════════════════════════════
#  PARTY  (Supplier + Customer)
# ═══════════════════════════════════════════════════════════════

@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = (
        "name", "party_type_badge", "company", "contact_person",
        "phone", "email", "balance_display", "total_amount_display",
        "status_badge", "is_removed",
    )
    search_fields = (
        "name", "contact_person", "phone", "email",
        "company__name", "uuid",
    )
    list_filter = ("party_type", "status", "is_removed", "company", "created_at")
    autocomplete_fields = ("company",)
    ordering = ("company__name", "party_type", "name")
    list_per_page = 25
    readonly_fields = ("uuid", "created_at", "updated_at")

    fieldsets = (
        (None, {
            "fields": ("company", "party_type", "uuid", "name", "logo"),
        }),
        ("Contact", {
            "fields": ("contact_person", "phone", "email", "address"),
        }),
        ("Balance", {
            "fields": ("balance", "total_amount"),
        }),
        ("Details", {
            "fields": ("description", "notes"),
        }),
        ("Status", {
            "fields": ("status", "is_removed"),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="Type")
    def party_type_badge(self, obj):
        colors = {
            "supplier": "#2563eb",   # blue
            "customer": "#7c3aed",   # purple
        }
        color = colors.get(obj.party_type, "#6b7280")
        return _badge(obj.get_party_type_display(), color)

    @admin.display(description="Balance", ordering="balance")
    def balance_display(self, obj):
        amt = obj.balance
        if amt > 0:
            color = "#dc2626"   # red = outstanding
        elif amt < 0:
            color = "#2563eb"   # blue = overpaid / advance
        else:
            color = "#16a34a"   # green = clear
        return format_html(
            '<span style="color:{}; font-weight:600;">{}</span>',
            color, _currency(amt),
        )

    @admin.display(description="Total (Lifetime)", ordering="total_amount")
    def total_amount_display(self, obj):
        return _currency(obj.total_amount)

    @admin.display(description="Status")
    def status_badge(self, obj):
        color = PARTY_STATUS_COLORS.get(obj.status, "#6b7280")
        return _badge(obj.get_status_display(), color)


# ═══════════════════════════════════════════════════════════════
#  ITEM
# ═══════════════════════════════════════════════════════════════

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "name", "company", "unit", "cost_price_display", "selling_price_display",
        "stock_display", "low_stock_indicator", "is_active",
        "created_at",
    )
    search_fields = ("name", "description", "company__name", "unit__name", "uuid")
    list_filter = ("is_active", "company", "unit", "created_at")
    autocomplete_fields = ("company", "unit")
    ordering = ("company__name", "name")
    list_per_page = 30
    readonly_fields = ("uuid", "is_low_stock_display", "created_at", "updated_at")

    fieldsets = (
        (None, {
            "fields": ("company", "uuid", "name", "description", "logo", "unit"),
        }),
        ("Pricing Defaults", {
            "fields": ("cost_price", "selling_price"),
        }),
        ("Stock", {
            "fields": (
                "quantity_in_stock", "low_stock_threshold", "is_low_stock_display",
            ),
        }),
        ("Status", {
            "fields": ("is_active",),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="CP")
    def cost_price_display(self, obj):
        return _currency(obj.cost_price)

    @admin.display(description="SP")
    def selling_price_display(self, obj):
        return _currency(obj.selling_price)

    @admin.display(description="Stock", ordering="quantity_in_stock")
    def stock_display(self, obj):
        return _currency(obj.quantity_in_stock)

    @admin.display(description="Low Stock?")
    def low_stock_indicator(self, obj):
        if obj.is_low_stock:
            return _badge("⚠ LOW", "#dc2626")
        return _badge("OK", "#16a34a")

    @admin.display(description="Low Stock Status")
    def is_low_stock_display(self, obj):
        threshold = obj.effective_low_stock_threshold
        if obj.is_low_stock:
            return format_html(
                '<span style="color:#dc2626; font-weight:600;">⚠ YES</span>'
                ' &nbsp;(stock: {} ≤ threshold: {})',
                obj.quantity_in_stock, threshold,
            )
        return format_html(
            '<span style="color:#16a34a; font-weight:600;">✓ No</span>'
            ' &nbsp;(stock: {} > threshold: {})',
            obj.quantity_in_stock, threshold,
        )


# ═══════════════════════════════════════════════════════════════
#  PURCHASE INVOICE  (Goods In)
#  with inline PurchaseItems
# ═══════════════════════════════════════════════════════════════

class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 1
    min_num = 1
    autocomplete_fields = ("item",)
    readonly_fields = ("line_total_display",)
    fields = ("item", "quantity", "cost_price", "selling_price", "line_total_display")

    @admin.display(description="Line Total")
    def line_total_display(self, obj):
        if obj.pk and obj.quantity and obj.cost_price:
            return _currency(obj.line_total)
        return "–"


@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    inlines = [PurchaseItemInline]

    list_display = (
        "reference_no", "supplier", "company", "date_received",
        "invoice_total_display", "total_paid_display",
        "balance_due_display", "payment_status_badge",
        "is_void", "created_at",
    )
    search_fields = (
        "reference_no", "supplier__name", "company__name", "notes",
    )
    list_filter = ("payment_status", "is_void", "company", "date_received", "created_at")
    autocomplete_fields = ("company", "supplier", "received_by")
    ordering = ("-date_received", "-created_at")
    list_per_page = 25
    readonly_fields = (
        "invoice_total_display_detail", "total_paid_display_detail",
        "balance_due_display_detail", "created_at", "updated_at",
    )
    date_hierarchy = "date_received"

    fieldsets = (
        (None, {
            "fields": (
                "company", "reference_no", "supplier",
                "date_received", "received_by",
            ),
        }),
        ("Payment Summary (auto-calculated)", {
            "fields": (
                "invoice_total_display_detail",
                "total_paid_display_detail",
                "balance_due_display_detail",
                "payment_status",
            ),
        }),
        ("Notes", {
            "fields": ("notes",),
        }),
        ("Void / Cancel", {
            "classes": ("collapse",),
            "fields": ("is_void", "void_reason"),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    # ── List display methods ──

    @admin.display(description="Invoice Total")
    def invoice_total_display(self, obj):
        return _currency(obj.invoice_total)

    @admin.display(description="Paid")
    def total_paid_display(self, obj):
        return _currency(obj.total_paid)

    @admin.display(description="Balance Due")
    def balance_due_display(self, obj):
        due = obj.balance_due
        if due > 0:
            return format_html(
                '<span style="color:#dc2626; font-weight:600;">{}</span>',
                _currency(due),
            )
        return format_html(
            '<span style="color:#16a34a; font-weight:600;">{}</span>',
            _currency(due),
        )

    @admin.display(description="Status")
    def payment_status_badge(self, obj):
        color = PAYMENT_STATUS_COLORS.get(obj.payment_status, "#6b7280")
        return _badge(obj.get_payment_status_display(), color)

    # ── Detail / form readonly methods ──

    @admin.display(description="Invoice Total")
    def invoice_total_display_detail(self, obj):
        if obj.pk:
            return format_html(
                '<strong style="font-size:14px;">{}</strong>', _currency(obj.invoice_total)
            )
        return "Save to calculate"

    @admin.display(description="Total Paid")
    def total_paid_display_detail(self, obj):
        if obj.pk:
            return _currency(obj.total_paid)
        return "–"

    @admin.display(description="Balance Due")
    def balance_due_display_detail(self, obj):
        if obj.pk:
            due = obj.balance_due
            color = "#dc2626" if due > 0 else "#16a34a"
            return format_html(
                '<strong style="font-size:14px; color:{};">{}</strong>',
                color, _currency(due),
            )
        return "–"


# ═══════════════════════════════════════════════════════════════
#  SALE INVOICE  (Goods Out)
#  with inline SaleItems
# ═══════════════════════════════════════════════════════════════

class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    min_num = 1
    autocomplete_fields = ("item",)
    readonly_fields = ("line_total_display",)
    fields = (
        "item", "quantity", "selling_price",
        "discount_type", "discount_amount", "line_total_display",
    )

    @admin.display(description="Line Total")
    def line_total_display(self, obj):
        if obj.pk and obj.quantity and obj.selling_price:
            return _currency(obj.line_total)
        return "–"


@admin.register(SaleInvoice)
class SaleInvoiceAdmin(admin.ModelAdmin):
    inlines = [SaleItemInline]

    list_display = (
        "reference_no", "customer", "company", "date_dispatched",
        "subtotal_display", "invoice_discount_display",
        "invoice_total_display", "total_paid_display",
        "balance_due_display", "payment_status_badge",
        "is_void", "created_at",
    )
    search_fields = (
        "reference_no", "customer__name", "company__name", "notes",
    )
    list_filter = ("payment_status", "is_void", "company", "date_dispatched", "created_at")
    autocomplete_fields = ("company", "customer", "dispatched_by")
    ordering = ("-date_dispatched", "-created_at")
    list_per_page = 25
    readonly_fields = (
        "subtotal_display_detail", "invoice_discount_display_detail",
        "invoice_total_display_detail", "total_paid_display_detail",
        "balance_due_display_detail", "created_at", "updated_at",
    )
    date_hierarchy = "date_dispatched"

    fieldsets = (
        (None, {
            "fields": (
                "company", "reference_no", "customer",
                "date_dispatched", "dispatched_by",
            ),
        }),
        ("Invoice-Level Discount", {
            "fields": ("discount_type", "discount_amount"),
        }),
        ("Payment Summary (auto-calculated)", {
            "fields": (
                "subtotal_display_detail",
                "invoice_discount_display_detail",
                "invoice_total_display_detail",
                "total_paid_display_detail",
                "balance_due_display_detail",
                "payment_status",
            ),
        }),
        ("Notes", {
            "fields": ("notes",),
        }),
        ("Void / Cancel", {
            "classes": ("collapse",),
            "fields": ("is_void", "void_reason"),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    # ── List display methods ──

    @admin.display(description="Subtotal")
    def subtotal_display(self, obj):
        return _currency(obj.subtotal)

    @admin.display(description="Discount")
    def invoice_discount_display(self, obj):
        val = obj.invoice_discount_value
        if val > 0:
            return format_html(
                '<span style="color:#d97706;">−{}</span>', _currency(val)
            )
        return "–"

    @admin.display(description="Total")
    def invoice_total_display(self, obj):
        return _currency(obj.invoice_total)

    @admin.display(description="Paid")
    def total_paid_display(self, obj):
        return _currency(obj.total_paid)

    @admin.display(description="Due")
    def balance_due_display(self, obj):
        due = obj.balance_due
        color = "#dc2626" if due > 0 else "#16a34a"
        return format_html(
            '<span style="color:{}; font-weight:600;">{}</span>',
            color, _currency(due),
        )

    @admin.display(description="Status")
    def payment_status_badge(self, obj):
        color = PAYMENT_STATUS_COLORS.get(obj.payment_status, "#6b7280")
        return _badge(obj.get_payment_status_display(), color)

    # ── Detail / form readonly methods ──

    @admin.display(description="Subtotal")
    def subtotal_display_detail(self, obj):
        if obj.pk:
            return _currency(obj.subtotal)
        return "Save to calculate"

    @admin.display(description="Invoice Discount")
    def invoice_discount_display_detail(self, obj):
        if obj.pk:
            val = obj.invoice_discount_value
            if val > 0:
                label = (
                    f"{obj.discount_amount}%" if obj.discount_type == "percentage"
                    else f"Flat {_currency(obj.discount_amount)}"
                )
                return format_html("−{} ({})", _currency(val), label)
            return "None"
        return "–"

    @admin.display(description="Invoice Total")
    def invoice_total_display_detail(self, obj):
        if obj.pk:
            return format_html(
                '<strong style="font-size:14px;">{}</strong>', _currency(obj.invoice_total)
            )
        return "Save to calculate"

    @admin.display(description="Total Paid")
    def total_paid_display_detail(self, obj):
        if obj.pk:
            return _currency(obj.total_paid)
        return "–"

    @admin.display(description="Balance Due")
    def balance_due_display_detail(self, obj):
        if obj.pk:
            due = obj.balance_due
            color = "#dc2626" if due > 0 else "#16a34a"
            return format_html(
                '<strong style="font-size:14px; color:{};">{}</strong>',
                color, _currency(due),
            )
        return "–"


# ═══════════════════════════════════════════════════════════════
#  SPOILAGE & LOSS
# ═══════════════════════════════════════════════════════════════

@admin.register(SpoilageLoss)
class SpoilageLossAdmin(admin.ModelAdmin):
    list_display = (
        "reference_no", "item", "company", "reason_badge",
        "quantity", "price_per_unit_display", "total_loss_display",
        "reported_by", "date_reported", "is_void",
    )
    search_fields = (
        "reference_no", "item__name", "company__name", "notes",
    )
    list_filter = ("reason", "is_void", "company", "date_reported", "created_at")
    autocomplete_fields = ("company", "item", "reported_by")
    ordering = ("-date_reported", "-created_at")
    list_per_page = 25
    readonly_fields = ("total_loss_readonly", "created_at", "updated_at")
    date_hierarchy = "date_reported"

    fieldsets = (
        (None, {
            "fields": (
                "company", "reference_no", "item", "reason",
            ),
        }),
        ("Details", {
            "fields": (
                "quantity", "price_per_unit", "total_loss_readonly",
                "date_reported", "reported_by",
            ),
        }),
        ("Notes", {
            "fields": ("notes",),
        }),
        ("Void / Cancel", {
            "classes": ("collapse",),
            "fields": ("is_void", "void_reason"),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="Reason")
    def reason_badge(self, obj):
        colors = {
            "expired": "#dc2626",   # red
            "damaged": "#d97706",   # amber
            "lost": "#7c3aed",      # purple
            "sample": "#2563eb",    # blue
        }
        color = colors.get(obj.reason, "#6b7280")
        return _badge(obj.get_reason_display(), color)

    @admin.display(description="Price/Unit")
    def price_per_unit_display(self, obj):
        return _currency(obj.price_per_unit)

    @admin.display(description="Total Loss")
    def total_loss_display(self, obj):
        return format_html(
            '<span style="color:#dc2626; font-weight:600;">{}</span>',
            _currency(obj.total_loss),
        )

    @admin.display(description="Total Loss")
    def total_loss_readonly(self, obj):
        if obj.pk and obj.quantity and obj.price_per_unit:
            return format_html(
                '<strong style="font-size:14px; color:#dc2626;">{}</strong>',
                _currency(obj.total_loss),
            )
        return "Save to calculate"


# ═══════════════════════════════════════════════════════════════
#  PAYMENT
# ═══════════════════════════════════════════════════════════════

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reference_no", "payment_type_badge", "party",
        "invoice_link", "amount_display",
        "payment_method_badge", "payment_status_badge",
        "received_by", "date_paid", "is_void",
    )
    search_fields = (
        "reference_no", "party__name", "company__name",
        "purchase_invoice__reference_no", "sale_invoice__reference_no",
        "notes",
    )
    list_filter = (
        "payment_type", "payment_method", "payment_status",
        "is_void", "company", "date_paid", "created_at",
    )
    autocomplete_fields = (
        "company", "party", "purchase_invoice",
        "sale_invoice", "received_by",
    )
    ordering = ("-date_paid", "-created_at")
    list_per_page = 25
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "date_paid"

    fieldsets = (
        (None, {
            "fields": (
                "company", "reference_no", "payment_type", "party",
            ),
        }),
        ("Invoice Link (optional)", {
            "description": "Link to a specific invoice. Leave blank for advance / general payments.",
            "fields": ("purchase_invoice", "sale_invoice"),
        }),
        ("Payment Details", {
            "fields": (
                "amount", "payment_method", "payment_status",
                "date_paid", "received_by",
            ),
        }),
        ("Notes", {
            "fields": ("notes",),
        }),
        ("Void / Cancel", {
            "classes": ("collapse",),
            "fields": ("is_void", "void_reason"),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="Type")
    def payment_type_badge(self, obj):
        colors = {
            "received": "#16a34a",   # green  (money coming in)
            "sent": "#dc2626",       # red    (money going out)
        }
        color = colors.get(obj.payment_type, "#6b7280")
        return _badge(obj.get_payment_type_display(), color)

    @admin.display(description="Invoice")
    def invoice_link(self, obj):
        """Show linked invoice reference or dash."""
        inv = obj.purchase_invoice or obj.sale_invoice
        if inv:
            return inv.reference_no
        return format_html('<span style="color:#9ca3af;">–</span>')

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        color = "#16a34a" if obj.payment_type == "received" else "#dc2626"
        prefix = "+" if obj.payment_type == "received" else "−"
        return format_html(
            '<span style="color:{}; font-weight:600;">{}{}</span>',
            color, prefix, _currency(obj.amount),
        )

    @admin.display(description="Method")
    def payment_method_badge(self, obj):
        colors = {
            "cash": "#16a34a",
            "online": "#2563eb",
            "cheque": "#d97706",
        }
        color = colors.get(obj.payment_method, "#6b7280")
        return _badge(obj.get_payment_method_display(), color)

    @admin.display(description="Status")
    def payment_status_badge(self, obj):
        color = PAYMENT_STATUS_COLORS.get(obj.payment_status, "#6b7280")
        return _badge(obj.get_payment_status_display(), color)


# ═══════════════════════════════════════════════════════════════
#  ADMIN SITE HEADER (optional branding)
# ═══════════════════════════════════════════════════════════════

admin.site.site_header = "Inventory Management System"
admin.site.site_title = "Inventory Admin"
admin.site.index_title = "Dashboard"