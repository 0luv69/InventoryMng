from django.contrib import admin
from .models import Product, Customer, GoodsIn, Sale, Payment


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit', 'cost_price', 'selling_price', 'quantity_in_stock')
    search_fields = ('name',)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'balance')
    search_fields = ('name', 'phone')


@admin.register(GoodsIn)
class GoodsInAdmin(admin.ModelAdmin):
    list_display = ('product', 'quantity', 'cost_price_at_entry', 'supplier_name', 'date')
    list_filter = ('date', 'product')


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('customer', 'product', 'quantity', 'selling_price', 'payment_type', 'date')
    list_filter = ('payment_type', 'date', 'product')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('customer', 'amount', 'date')
    list_filter = ('date',)