from django.contrib import admin
from .models import Warehouse, StockBatch, StockMovement

@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'location', 'is_active')
    search_fields = ('name',)

@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = ('item', 'warehouse', 'batch_no', 'expiry_date', 'quantity', 'landing_cost')
    list_filter = ('warehouse',)
    search_fields = ('item__name', 'batch_no')

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'item', 'warehouse', 'movement_type', 'quantity', 'reference_model', 'created_by')
    list_filter = ('movement_type', 'warehouse')
    readonly_fields = [field.name for field in StockMovement._meta.fields] # Make it read-only in admin