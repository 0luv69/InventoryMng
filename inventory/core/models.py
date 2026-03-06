import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


# ═══════════════════════════════════════════════════════════════
#  SHARED CHOICES
# ═══════════════════════════════════════════════════════════════

class PaymentStatus(models.TextChoices):
    PAID = "paid", "Paid"
    PARTIAL = "partial", "Partial"
    UNPAID = "unpaid", "Unpaid"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    ONLINE = "online", "Online"
    CHEQUE = "cheque", "Cheque"


class DiscountType(models.TextChoices):
    PERCENTAGE = "percentage", "Percentage"
    FIXED = "fixed", "Fixed Amount"


# ═══════════════════════════════════════════════════════════════
#  ABSTRACT BASE
# ══��════════════════════════════════════════════════════════════

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ═══════════════════════════════════════════════════════════════
#  COMPANY
# ═══════════════════════════════════════════════════════════════

class Company(TimeStampedModel):
    CURRENCY_CHOICES = [
        ("NPR", "Nepalese Rupee"),
        ("INR", "Indian Rupee"),
        ("USD", "US Dollar"),
    ]

    # ── Identity ──
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    logo = models.ImageField(upload_to="company_logos/", null=True, blank=True)

    # ── Contact ──
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, blank=True)

    # ── Financial ──
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="NPR")
    tax_id = models.CharField("Tax / PAN Number", max_length=50, blank=True)

    # ── Settings ──
    default_low_stock_threshold = models.PositiveIntegerField(
        default=20, validators=[MinValueValidator(1)]
    )
    fiscal_year_start_month = models.PositiveIntegerField(
        default=7,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Month number (1=Jan … 7=Jul/Shrawan … 12=Dec)"
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ═══════════════════════════════════════════════════════════════
#  USER PROFILE
# ═══════════════════════════════════════════════════════════════

class UserProfile(TimeStampedModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="members",
        null=True, blank=True
    )
    phone_num = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    is_owner = models.BooleanField(default=False)

    def __str__(self):
        company_name = self.company.name if self.company else "No Company"
        return f"{self.user.get_full_name() or self.user.username} @ {company_name}"


# ═══════════════════════════════════════════════════════════════
#  USER SESSION
# ═══════════════════════════════════════════════════════════════

class UserSession(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions"
    )
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    session_key = models.CharField(max_length=40)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    other_info = models.TextField(blank=True)
    last_activity = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} – {self.session_key}"


# ═══════════════════════════════════════════════════════════════
#  REQUEST DEMO (landing page)
# ══════���════════════════════════════════════════════════════════

class RequestDemo(TimeStampedModel):
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    message = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} ({self.email})"


# ═══════════════════════════════════════════════════════════════
#  UNIT OF MEASUREMENT
# ═══════════════════════════════════════════════════════════════

class Unit(TimeStampedModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="units")
    name = models.CharField(max_length=50)
    short_name = models.CharField(max_length=10)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="uniq_unit_name_per_company"
            ),
            models.UniqueConstraint(
                fields=["company", "short_name"], name="uniq_unit_short_per_company"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.short_name})"


# ═══════════════════════════════════════════════════════════════
#  PARTY  (Supplier + Customer in one table)
# ═══════════════════════════════════════════════════════════════

class Party(TimeStampedModel):
    class PartyType(models.TextChoices):
        SUPPLIER = "supplier", "Supplier"
        CUSTOMER = "customer", "Customer"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="parties")
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    party_type = models.CharField(max_length=10, choices=PartyType.choices)

    # ── Identity ──
    name = models.CharField(max_length=200)
    logo = models.ImageField(upload_to="party_logos/", null=True, blank=True)

    # ── Contact ──
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    # ── Balance ──
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Supplier: you owe them (payable). Customer: they owe you (receivable)."
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Lifetime total paid (supplier) or received (customer)."
    )

    # ── Meta ──
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    is_removed = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "parties"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "party_type", "name"],
                name="uniq_party_name_per_type_company",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_party_type_display()})"


# ═══════════════════════════════════════════════════════════════
#  ITEM  (Product / Inventory Item)
# ═══════════════════════════════════════════════════════════════

class Item(TimeStampedModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="items")
    supplier = models.ForeignKey(
        Party, on_delete=models.PROTECT, related_name="purchase_invoices",
        limit_choices_to={"party_type": Party.PartyType.SUPPLIER},
    )
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="item_images/", null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="items")

    # ── Pricing defaults ──
    cost_price = models.DecimalField(
        "Default Cost Price", max_digits=10, decimal_places=2, default=0,
        help_text="Default price you pay to buy this item"
    )
    selling_price = models.DecimalField(
        "Default Selling Price", max_digits=10, decimal_places=2, default=0,
        help_text="Default price you sell this item at"
    )

    # ── Stock ──
    quantity_in_stock = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    low_stock_threshold = models.PositiveIntegerField(
        default=0, help_text="0 = use company default threshold"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="uniq_item_name_per_company"
            ),
        ]

    @property
    def effective_low_stock_threshold(self):
        """Item threshold if set, otherwise company default."""
        return self.low_stock_threshold or self.company.default_low_stock_threshold

    @property
    def is_low_stock(self):
        return self.quantity_in_stock <= self.effective_low_stock_threshold

    def __str__(self):
        return self.name


# ═══════════════════════════════════════════════════════════════
#  PURCHASE INVOICE  (Goods In – header)
# ══════════���════════════════════════════════════════════════════

class PurchaseInvoice(TimeStampedModel):
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="purchase_invoices"
    )
    reference_no = models.CharField(max_length=50)
    date_received = models.DateField(default=timezone.now)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="purchase_invoices_received",
    )
    notes = models.TextField(blank=True)

    # ── Payment status (auto-updated when Payment is saved) ──
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )

    # ── Soft delete ──
    is_void = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-date_received", "-created_at"]
        verbose_name = "Purchase Invoice"
        verbose_name_plural = "Purchase Invoices"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "reference_no"],
                name="uniq_purchase_ref_per_company",
            ),
        ]

    # ── Computed helpers ──

    @property
    def invoice_total(self):
        """Sum of all line totals."""
        return sum(line.line_total for line in self.lines.all())

    @property
    def total_paid(self):
        """Sum of all non-voided payments linked to this invoice."""
        return (
            self.payments.filter(is_void=False)
            .aggregate(total=models.Sum("amount"))["total"]
            or 0
        )

    @property
    def balance_due(self):
        return self.invoice_total - self.total_paid

    def update_payment_status(self):
        """Call this after a Payment is created / updated / voided."""
        paid = self.total_paid
        total = self.invoice_total

        if total <= 0:
            new_status = PaymentStatus.UNPAID
        elif paid <= 0:
            new_status = PaymentStatus.UNPAID
        elif paid >= total:
            new_status = PaymentStatus.PAID
        else:
            new_status = PaymentStatus.PARTIAL

        if self.payment_status != new_status:
            self.payment_status = new_status
            self.save(update_fields=["payment_status", "updated_at"])

    def __str__(self):
        return f"{self.reference_no} – {self.supplier.name}"


# ═══════════════════════════════════════════════════════════════
#  PURCHASE ITEM  (Goods In – line items)
# ═══════════════════════════════════════════════════════════════

class PurchaseItem(TimeStampedModel):
    invoice = models.ForeignKey(
        PurchaseInvoice, on_delete=models.CASCADE, related_name="lines"
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="purchase_lines")
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Cost price per unit for this batch"
    )
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Updated selling price for this batch (optional)"
    )

    @property
    def line_total(self):
        return self.quantity * self.cost_price

    def __str__(self):
        return f"{self.item.name} × {self.quantity}"


# ═══════════════════════════════════════════════════════════════
#  SALE INVOICE  (Goods Out – header)
# ═══════════════════════════════════════════════════════════════

class SaleInvoice(TimeStampedModel):
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="sale_invoices"
    )
    reference_no = models.CharField(max_length=50)
    customer = models.ForeignKey(
        Party, on_delete=models.PROTECT, related_name="sale_invoices",
        limit_choices_to={"party_type": Party.PartyType.CUSTOMER},
    )
    date_dispatched = models.DateField(default=timezone.now)
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="sale_invoices_dispatched",
    )
    notes = models.TextField(blank=True)

    # ── Invoice-level discount ──
    discount_type = models.CharField(
        max_length=12, choices=DiscountType.choices, default=DiscountType.FIXED
    )
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Payment status (auto-updated when Payment is saved) ──
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )

    # ── Soft delete ──
    is_void = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-date_dispatched", "-created_at"]
        verbose_name = "Sale Invoice"
        verbose_name_plural = "Sale Invoices"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "reference_no"],
                name="uniq_sale_ref_per_company",
            ),
        ]

    # ── Computed helpers ──

    @property
    def subtotal(self):
        """Sum of all line totals (after per-line discounts)."""
        return sum(line.line_total for line in self.lines.all())

    @property
    def invoice_discount_value(self):
        """Invoice-level discount converted to currency amount."""
        if self.discount_type == DiscountType.PERCENTAGE:
            return self.subtotal * (self.discount_amount / 100)
        return self.discount_amount

    @property
    def invoice_total(self):
        return self.subtotal - self.invoice_discount_value

    @property
    def total_paid(self):
        return (
            self.payments.filter(is_void=False)
            .aggregate(total=models.Sum("amount"))["total"]
            or 0
        )

    @property
    def balance_due(self):
        return self.invoice_total - self.total_paid

    def update_payment_status(self):
        """Call this after a Payment is created / updated / voided."""
        paid = self.total_paid
        total = self.invoice_total

        if total <= 0:
            new_status = PaymentStatus.UNPAID
        elif paid <= 0:
            new_status = PaymentStatus.UNPAID
        elif paid >= total:
            new_status = PaymentStatus.PAID
        else:
            new_status = PaymentStatus.PARTIAL

        if self.payment_status != new_status:
            self.payment_status = new_status
            self.save(update_fields=["payment_status", "updated_at"])

    def __str__(self):
        return f"{self.reference_no} – {self.customer.name}"


# ═══════════════════════════════════════════════════════════════
#  SALE ITEM  (Goods Out – line items)
# ═══════════════════════════════════════════════════════════════

class SaleItem(TimeStampedModel):
    invoice = models.ForeignKey(
        SaleInvoice, on_delete=models.CASCADE, related_name="lines"
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="sale_lines")
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Selling price per unit for this sale"
    )

    # ── Line-level discount ──
    discount_type = models.CharField(
        max_length=12, choices=DiscountType.choices, default=DiscountType.FIXED
    )
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    @property
    def gross_total(self):
        return self.quantity * self.selling_price

    @property
    def discount_value(self):
        """Line discount converted to currency amount."""
        if self.discount_type == DiscountType.PERCENTAGE:
            return self.gross_total * (self.discount_amount / 100)
        return self.discount_amount

    @property
    def line_total(self):
        return self.gross_total - self.discount_value

    def __str__(self):
        return f"{self.item.name} × {self.quantity}"


# ═══════════════════════════════════════════════════════════════
#  SPOILAGE & LOSS
# ═══════════════════════════════════════════════════════════════

class SpoilageLoss(TimeStampedModel):
    class Reason(models.TextChoices):
        EXPIRED = "expired", "Expired"
        DAMAGED = "damaged", "Damaged"
        LOST = "lost", "Lost"
        SAMPLE = "sample", "Sample / Giveaway"

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="spoilage_losses"
    )
    reference_no = models.CharField(max_length=50)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="spoilage_losses")
    reason = models.CharField(max_length=10, choices=Reason.choices)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    price_per_unit = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Cost price per unit at the time of loss"
    )
    date_reported = models.DateField(default=timezone.now)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="spoilage_losses_reported",
    )
    notes = models.TextField(blank=True)

    # ── Soft delete ──
    is_void = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-date_reported", "-created_at"]
        verbose_name = "Spoilage & Loss"
        verbose_name_plural = "Spoilage & Losses"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "reference_no"],
                name="uniq_spoilage_ref_per_company",
            ),
        ]

    @property
    def total_loss(self):
        return self.quantity * self.price_per_unit

    def __str__(self):
        return f"{self.item.name} – {self.get_reason_display()} × {self.quantity}"


# ═══════════════════════════════════════════════════════════════
#  PAYMENT
# ═══════════════════════════════════════════════════════════════

class Payment(TimeStampedModel):
    class PaymentType(models.TextChoices):
        RECEIVED = "received", "Received"   # from customer
        SENT = "sent", "Sent"               # to supplier

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="payments"
    )
    reference_no = models.CharField(max_length=50)
    payment_type = models.CharField(max_length=10, choices=PaymentType.choices)
    party = models.ForeignKey(
        Party, on_delete=models.PROTECT, related_name="payments"
    )

    # ── Optional invoice links ──
    purchase_invoice = models.ForeignKey(
        PurchaseInvoice, on_delete=models.PROTECT,
        null=True, blank=True, related_name="payments",
    )
    sale_invoice = models.ForeignKey(
        SaleInvoice, on_delete=models.PROTECT,
        null=True, blank=True, related_name="payments",
    )

    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    date_paid = models.DateField(default=timezone.now)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="payments_handled",
    )
    payment_method = models.CharField(
        max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PAID
    )
    notes = models.TextField(blank=True)

    # ── Soft delete ──
    is_void = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-date_paid", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "reference_no"],
                name="uniq_payment_ref_per_company",
            ),
        ]

    def clean(self):
        """
        Validation rules:
        - sent     → party must be supplier, only purchase_invoice allowed
        - received → party must be customer, only sale_invoice allowed
        - cannot link both invoices at the same time
        """
        errors = {}

        if self.payment_type == self.PaymentType.SENT:
            if self.party_id and self.party.party_type != Party.PartyType.SUPPLIER:
                errors["party"] = "Sent payments must be linked to a supplier."
            if self.sale_invoice:
                errors["sale_invoice"] = "Sent payments cannot link to a sale invoice."

        elif self.payment_type == self.PaymentType.RECEIVED:
            if self.party_id and self.party.party_type != Party.PartyType.CUSTOMER:
                errors["party"] = "Received payments must be linked to a customer."
            if self.purchase_invoice:
                errors["purchase_invoice"] = "Received payments cannot link to a purchase invoice."

        if self.purchase_invoice and self.sale_invoice:
            errors["purchase_invoice"] = "Cannot link to both a purchase and sale invoice."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.reference_no} – {self.get_payment_type_display()} – {self.amount}"