from django.db import models
from apps.core.models import BaseModel
import uuid
import functools
from django.core.validators import MinValueValidator
from decimal import Decimal

# ==========================================
# 1. CATEGORY
# ==========================================
class Category(BaseModel):
    """ Represents a category for items, e.g., Electronics, Groceries """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        ordering = ['name']
        verbose_name_plural = 'Categories'
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], condition=~models.Q(is_deleted=True), name='uniq_category_per_company')
        ]

    def __str__(self):
        return self.name

# ==========================================
# 2. UNIT OF MEASUREMENT (UOM)
# ==========================================
class Unit(BaseModel):
    """ Represents a unit of measurement for items, e.g., Pieces, Carton, Kg """
    name = models.CharField(max_length=50, help_text="e.g., Pieces, Carton, Kg")
    short_name = models.CharField(max_length=10, help_text="e.g., Pcs, Ctn, Kg")

    class Meta(BaseModel.Meta):
        ordering = ['name']
        constraints = [
            # FIX: Added ~Q(is_deleted=True) so deleted units can be recreated
            models.UniqueConstraint(fields=['company', 'name'], condition=~models.Q(is_deleted=True), name='uniq_unit_name_per_company')
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
    base_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='items')
    barcode = models.CharField(max_length=100, blank=True, db_index=True)
    
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    image = models.ImageField(upload_to='item_images/', null=True, blank=True)
    default_supplier = models.ForeignKey(
        'parties.Party', on_delete=models.SET_NULL, null=True, blank=True, 
        related_name='supplied_items', limit_choices_to={'is_supplier': True}
    )
    
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    delete_reason = models.TextField(blank=True, null=True, help_text="Reason for deleting/discontinuing the item")
    low_stock_threshold = models.PositiveIntegerField(default=10)

    # FIX: Use cached_property to prevent 4 DB queries per save
    @functools.cached_property
    def is_locked(self):
        from apps.transactions.models import PurchaseItemLine, SaleItemLine
        return PurchaseItemLine.objects.filter(item=self).exists() or SaleItemLine.objects.filter(item=self).exists()

    @property
    def total_stock(self):
        from apps.inventory.models import StockBatch
        total = StockBatch.objects.filter(item=self).aggregate(total=models.Sum('quantity'))['total']
        return total or 0

    class Meta(BaseModel.Meta):
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], condition=~models.Q(is_deleted=True), name='uniq_item_name_per_company'),
            # FIX: Added ~Q(is_deleted=True) so deleted item barcodes can be reused
            models.UniqueConstraint(fields=['company', 'barcode'], condition=~models.Q(barcode='') & ~models.Q(is_deleted=True), name='uniq_item_barcode_per_company'),
        ]

    def __str__(self):
        return self.name

# ==========================================
# 4. ITEM UOM CONVERSIONS
# ==========================================
class ItemUOM(BaseModel):
    """ Conversion factors for items to different units of measurement """


    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='uom_conversions')
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='item_conversions')
    conversion_factor = models.DecimalField(
        max_digits=10, decimal_places=2, 
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="e.g., If Base is Pcs and this is Carton, factor = 12"
    )
    barcode = models.CharField(max_length=100, blank=True, db_index=True)

    class Meta(BaseModel.Meta):
        constraints = [ 
            models.UniqueConstraint(fields=['item', 'unit'], name='uniq_item_uom'),
            # FIX: Added ~Q(is_deleted=True) so deleted UOM barcodes can be reused
            models.UniqueConstraint(fields=['company', 'barcode'], condition=~models.Q(barcode='') & ~models.Q(is_deleted=True), name='uniq_itemuom_barcode_per_company'),
        ]

# ==========================================
# 5. PRICE TIERS & ITEM PRICES
# ==========================================
class PriceTier(BaseModel):
    """ Custom price tags like MRP, Wholesale, Major Buyer """

    name = models.CharField(max_length=50)
    is_default = models.BooleanField(default=False)

    class Meta(BaseModel.Meta):
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], condition=~models.Q(is_deleted=True), name='uniq_pricetier_per_company')
        ]
    def __str__(self):
        return self.name

class ItemPrice(BaseModel):
    """ Stores the actual price of an item for a specific price tier """

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='prices')
    price_tier = models.ForeignKey(PriceTier, on_delete=models.CASCADE, related_name='item_prices')
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='item_prices')
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta(BaseModel.Meta):
        constraints = [
            # FIX: Renamed constraint to match the new unit field
            models.UniqueConstraint(fields=['item', 'price_tier', 'unit'], name='uniq_item_pricetier_unit')
        ]