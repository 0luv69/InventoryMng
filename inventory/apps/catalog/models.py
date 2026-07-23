from django.db import models
from apps.core.models import BaseModel
import uuid

# ==========================================
# 1. CATEGORY
# ==========================================
class Category(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Categories'
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='uniq_category_per_company')
        ]

    def __str__(self):
        return self.name


# ==========================================
# 2. UNIT OF MEASUREMENT (UOM)
# ==========================================
class Unit(BaseModel):
    name = models.CharField(max_length=50, help_text="e.g., Pieces, Carton, Kg")
    short_name = models.CharField(max_length=10, help_text="e.g., Pcs, Ctn, Kg")

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='uniq_unit_name_per_company')
        ]

    def __str__(self):
        return f"{self.name} ({self.short_name})"


# ==========================================
# 3. ITEM (PRODUCT)
# ==========================================
class Item(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    
    # The Base Unit is the smallest unit (e.g., Piece). Stock is ALWAYS tracked in this unit.
    base_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='items')
    
    # Barcodes for POS/Scanner
    barcode = models.CharField(max_length=100, blank=True, db_index=True)
    
    # Moving Average Cost (Auto-calculated by system during purchases)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    is_removed = models.BooleanField(default=False) # Soft delete
    
    # Reorder level
    low_stock_threshold = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='uniq_item_name_per_company')
        ]

    def __str__(self):
        return self.name


# ==========================================
# 4. ITEM UOM CONVERSIONS
# ==========================================
class ItemUOM(BaseModel):
    """ Defines how many base units make up a larger unit for a specific item. """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='uom_conversions')
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='item_conversions')
    conversion_factor = models.DecimalField(
        max_digits=10, decimal_places=2, 
        help_text="e.g., If Base is Pcs and this is Carton, factor = 12"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['item', 'unit'], name='uniq_item_uom')
        ]


# ==========================================
# 5. PRICE TIERS & ITEM PRICES
# ==========================================
class PriceTier(BaseModel):
    """ Custom price tags like MRP, Wholesale, Major Buyer """
    name = models.CharField(max_length=50)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='uniq_pricetier_per_company')
        ]

    def __str__(self):
        return self.name

class ItemPrice(BaseModel):
    """ Stores the actual price of an item for a specific price tier """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='prices')
    price_tier = models.ForeignKey(PriceTier, on_delete=models.CASCADE, related_name='item_prices')
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['item', 'price_tier'], name='uniq_item_pricetier')
        ]