from django.db import models
from django.conf import settings
from apps.core.models import BaseModel
from apps.catalog.models import Item 
from apps.parties.models import Party

# ==========================================
# 1. WAREHOUSE (GODOWN)
# ==========================================
class Warehouse(BaseModel):
    """ Represents a physical location where stock is kept """
    name = models.CharField(max_length=100, help_text="e.g., Main Godown, Counter")
    location = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='uniq_warehouse_per_company')
        ]

    def __str__(self):
        return self.name


# ==========================================
# 2. STOCK BATCH (THE ACTUAL PHYSICAL STOCK)
# ==========================================
class StockBatch(BaseModel):
    """
    Tracks the exact quantity of an Item in a specific Warehouse 
    with a specific Batch No and Expiry Date.
    """
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='stock_batches')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='stock_batches')
    
    batch_no = models.CharField(max_length=50, blank=True, null=True, help_text="Leave blank if item has no batch")
    expiry_date = models.DateField(null=True, blank=True)
    
    # This is the ACTUAL stock. The Item.quantity_in_stock will be a cached sum of this.
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # The cost price at which THIS specific batch was bought (For accurate profit calculation)
    landing_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    supplier = models.ForeignKey(
        Party, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='stock_batches',
        limit_choices_to={'is_supplier': True}
    )

    class Meta:
        ordering = ['expiry_date'] # FEFO: First Expired, First Out ordering
        constraints = [
            # Prevent duplicate batch entries for the same item in the same warehouse
            models.UniqueConstraint(
                fields=['company', 'item', 'warehouse', 'batch_no'], 
                name='uniq_stockbatch_per_warehouse',
                condition=models.Q(batch_no__isnull=False) # Only apply if batch_no is not null
            )
        ]

    def __str__(self):
        return f"{self.item.name} - {self.warehouse.name} (Batch: {self.batch_no or 'N/A'})"


# ==========================================
# 3. STOCK MOVEMENT (THE AUDIT TRAIL)
# ==========================================
class StockMovement(BaseModel):
    """
    An immutable ledger of every single time stock was added, removed, or moved.
    This is how we track "Who did what and when".
    """
    class MovementType(models.TextChoices):
        PURCHASE = 'purchase', 'Purchase (Goods In)'
        SALE = 'sale', 'Sale (Goods Out)'
        SALE_RETURN = 'sale_return', 'Sale Return'
        SPOILAGE = 'spoilage', 'Spoilage / Loss'
        OPENING = 'opening', 'Opening Stock'
        ADJUSTMENT = 'adjustment', 'Manual Adjustment'

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='movements')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='movements')
    batch_no = models.CharField(max_length=50, blank=True, null=True)
    
    movement_type = models.CharField(max_length=15, choices=MovementType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, help_text="Positive for IN, Negative for OUT")
    
    # Snapshot of the balance right after this movement (useful for reports)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Link to the transaction that caused this movement (e.g., the Invoice ID)
    reference_model = models.CharField(max_length=50, blank=True, help_text="e.g., 'SaleInvoice'")
    reference_id = models.CharField(max_length=50, blank=True)
    
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'item', '-created_at']),
            models.Index(fields=['company', 'warehouse', '-created_at']),
        ]

    def __str__(self):
        return f"{self.movement_type} - {self.item.name} - Qty: {self.quantity}"