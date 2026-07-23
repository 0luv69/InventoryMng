from django.contrib import admin
from .models import Category, Unit, Item, ItemUOM, PriceTier, ItemPrice

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'company')

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name', 'company')

class ItemUOMInline(admin.TabularInline):
    model = ItemUOM
    extra = 1

class ItemPriceInline(admin.TabularInline):
    model = ItemPrice
    extra = 1

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'base_unit', 'barcode', 'cost_price', 'status')
    list_filter = ('status', 'category')
    search_fields = ('name', 'barcode')
    inlines = [ItemUOMInline, ItemPriceInline]

@admin.register(PriceTier)
class PriceTierAdmin(admin.ModelAdmin):
    list_display = ('name', 'company')