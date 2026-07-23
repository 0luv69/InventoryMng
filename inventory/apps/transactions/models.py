from django.db import models
from apps.core.models import BaseModel
from apps.parties.models import Party
from apps.catalog.models import Item, Unit, PriceTier
from apps.inventory.models import Warehouse
# ==========================================
# SHARED CHOICES
# ==========================================
class InvoiceStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    FINALIZED = 'finalized', 'Finalized'
    VOID = 'void', 'Void'

class PaymentStatus(models.TextChoices):
    UNPAID = 'unpaid', 'Unpaid'
    PARTIAL = 'partial', 'Partial'
    PAID = 'paid', 'Paid'

class DiscountType(models.TextChoices):
    PERCENTAGE = 'percentage', 'Percentage'
    FIXED = 'fixed', 'Fixed Amount'


# ==========================================
# 1. PURCHASE INVOICE (Goods In)
# ==========================================
class PurchaseInvoice(BaseModel):
    reference_no = models.CharField(max_length=50)
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT, related_name='purchase_invoices', limit_choices_to={'is_supplier': True})
    date_received = models.DateField()
    
    # Financials
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.FIXED)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="VAT 13%")
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Statuses
    invoice_status = models.CharField(max_length=10, choices=InvoiceStatus.choices, default=InvoiceStatus.FINALIZED)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date_received', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['company', 'reference_no'], name='uniq_purchase_ref_per_company')
        ]

    def __str__(self):
        return f"{self.reference_no} - {self.supplier.name}"


class PurchaseItemLine(BaseModel):
    """ Line items for a Purchase Invoice """
    invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='purchase_lines')

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='%(class)s_lines')
    
    # UOM Selection (Allows buying in Carton while Base Unit is Pcs)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    conversion_factor = models.DecimalField(max_digits=10, decimal_places=2, default=1, help_text="Qty in Base Units = Quantity * Factor")
    
    # Pricing
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.FIXED)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Batch tracking (Auto-creates StockBatch based on these fields)
    batch_no = models.CharField(max_length=50, blank=True, null=True)
    expiry_date = models.DateField(null=True, blank=True)


    def __str__(self):
        return f"{self.item.name} - {self.quantity} {self.unit.short_name}"

    def save(self, *args, **kwargs):
        # Calculate Line Gross Total
        price = self.cost_price if hasattr(self, 'cost_price') else self.selling_price
        gross_total = self.quantity * price
        
        # Calculate Line Discount
        if self.discount_type == 'percentage':
            discount_val = gross_total * (self.discount_amount / 100)
        else:
            discount_val = self.discount_amount
            
        self.line_total = gross_total - discount_val
        super().save(*args, **kwargs)


# ==========================================
# 2. SALE INVOICE (Goods Out)
# ==========================================
class SaleInvoice(BaseModel):
    reference_no = models.CharField(max_length=50)
    customer = models.ForeignKey(Party, on_delete=models.PROTECT, related_name='sale_invoices', limit_choices_to={'is_customer': True})
    date_dispatched = models.DateField()
    
    # Optional: Apply a specific Price Tier to this whole invoice
    price_tier = models.ForeignKey(PriceTier, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Financials
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.FIXED)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="VAT 13%")
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Statuses
    invoice_status = models.CharField(max_length=10, choices=InvoiceStatus.choices, default=InvoiceStatus.FINALIZED)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date_dispatched', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['company', 'reference_no'], name='uniq_sale_ref_per_company')
        ]


    def clean(self):
        from django.core.exceptions import ValidationError
        from decimal import Decimal
        
        # Only check credit limit for finalized invoices
        if self.invoice_status == 'finalized' and self.customer_id:
            # Get the customer's current balance
            current_balance = self.customer.balance
            
            # If editing an existing invoice, we must exclude its old total from the current balance
            if self.pk:
                old_total = SaleInvoice.objects.get(pk=self.pk).grand_total
                current_balance -= old_total
            
            # Check against credit limit (0 means no limit)
            if self.customer.credit_limit > 0:
                new_potential_balance = current_balance + self.grand_total
                if new_potential_balance > self.customer.credit_limit:
                    raise ValidationError(
                        f"Credit Limit Exceeded! {self.customer.name} has a limit of Rs. {self.customer.credit_limit}. "
                        f"Current Balance: Rs. {current_balance}. "
                        f"This invoice total of Rs. {self.grand_total} pushes them to Rs. {new_potential_balance}."
                    )

    def __str__(self):
        return f"{self.reference_no} - {self.customer.name}"



class SaleItemLine(BaseModel):
    """ Line items for a Sale Invoice """
    invoice = models.ForeignKey(SaleInvoice, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='sale_lines')

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='%(class)s_lines')
    
    # UOM Selection (Allows selling in Carton while Base Unit is Pcs)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    conversion_factor = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    
    # Pricing (Defaults to Item Price, but can be overridden)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.FIXED)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # If FEFO (First Expired First Out) is used, system assigns stock from specific batches here
    assigned_batch_no = models.CharField(max_length=50, blank=True, null=True, help_text="Auto-filled by FEFO logic")

    def __str__(self):
        return f"{self.item.name} - {self.quantity} {self.unit.short_name}"

    def save(self, *args, **kwargs):
        # Calculate Line Gross Total
        price = self.cost_price if hasattr(self, 'cost_price') else self.selling_price
        gross_total = self.quantity * price
        
        # Calculate Line Discount
        if self.discount_type == 'percentage':
            discount_val = gross_total * (self.discount_amount / 100)
        else:
            discount_val = self.discount_amount
            
        self.line_total = gross_total - discount_val
        super().save(*args, **kwargs)




# ==========================================
# 3. PAYMENTS & ALLOCATIONS
# ==========================================
class Payment(BaseModel):
    class PaymentType(models.TextChoices):
        RECEIVED = 'received', 'Received (From Customer)'
        SENT = 'sent', 'Sent (To Supplier)'

    reference_no = models.CharField(max_length=50)
    payment_type = models.CharField(max_length=10, choices=PaymentType.choices)
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name='payments')
    
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date_paid = models.DateField()
    method = models.CharField(max_length=20, default='cash') # cash, online, cheque
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date_paid', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['company', 'reference_no'], name='uniq_payment_ref_per_company')
        ]

    def __str__(self):
        return f"{self.reference_no} - {self.amount}"


class PaymentAllocation(BaseModel):
    """ Links a lump-sum payment to specific invoices """
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='allocations')
    
    # Only one of these will be used depending on the payment type
    sale_invoice = models.ForeignKey(SaleInvoice, on_delete=models.CASCADE, null=True, blank=True, related_name='allocations')
    purchase_invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, null=True, blank=True, related_name='allocations')
    
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.payment.payment_type == 'received' and self.purchase_invoice:
            raise ValidationError("Received payments cannot be linked to purchase invoices.")
        if self.payment.payment_type == 'sent' and self.sale_invoice:
            raise ValidationError("Sent payments cannot be linked to sale invoices.")




# ==========================================
# 4. SALES RETURNS & SPOILAGE
# ==========================================
class SpoilageReason(models.TextChoices):
    EXPIRED = 'expired', 'Expired'
    DAMAGED = 'damaged', 'Damaged'
    LOST = 'lost', 'Lost'
    SAMPLE = 'sample', 'Sample / Giveaway'

class SalesReturn(BaseModel):
    reference_no = models.CharField(max_length=50)
    customer = models.ForeignKey(Party, on_delete=models.PROTECT, related_name='sales_returns', limit_choices_to={'is_customer': True})
    original_invoice = models.ForeignKey(SaleInvoice, on_delete=models.SET_NULL, null=True, blank=True)
    date_returned = models.DateField()
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Value of returned goods")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date_returned', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['company', 'reference_no'], name='uniq_salesreturn_ref_per_company')
        ]

    def __str__(self):
        return f"Return {self.reference_no} - {self.customer.name}"


class SalesReturnItemLine(BaseModel):
    """ Line items for a Sales Return """
    return_invoice = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='return_lines')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    conversion_factor = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price at which it was sold")
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # If True, item is broken/expired and goes to Spoilage. If False, goes back to sellable stock.
    is_spoiled = models.BooleanField(default=False)
    batch_no = models.CharField(max_length=50, blank=True, null=True, help_text="Batch the item is returned to")

    def save(self, *args, **kwargs):
        self.line_total = self.quantity * self.cost_price
        super().save(*args, **kwargs)


class SpoilageLoss(BaseModel):
    """ Direct spoilage from the warehouse (not from a customer return) """
    reference_no = models.CharField(max_length=50)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='spoilages')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    batch_no = models.CharField(max_length=50, blank=True, null=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=20, choices=SpoilageReason.choices)
    date_reported = models.DateField()
    total_loss_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date_reported', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['company', 'reference_no'], name='uniq_spoilage_ref_per_company')
        ]

    def save(self, *args, **kwargs):
        self.total_loss_value = self.quantity * self.item.cost_price
        super().save(*args, **kwargs)