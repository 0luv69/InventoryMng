from django.contrib import admin
from .models import (
    PurchaseInvoice, PurchaseItemLine, 
    SaleInvoice, SaleItemLine,
    Payment, PaymentAllocation,
    SalesReturn, SalesReturnItemLine,
    SpoilageLoss
)

class PurchaseItemLineInline(admin.TabularInline):
    model = PurchaseItemLine
    extra = 1

@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = ('reference_no', 'company', 'supplier', 'date_received', 'grand_total', 'invoice_status', 'payment_status')
    list_filter = ('invoice_status', 'payment_status')
    search_fields = ('reference_no', 'supplier__name')
    inlines = [PurchaseItemLineInline]

class SaleItemLineInline(admin.TabularInline):
    model = SaleItemLine
    extra = 1

@admin.register(SaleInvoice)
class SaleInvoiceAdmin(admin.ModelAdmin):
    list_display = ('reference_no', 'company', 'customer', 'date_dispatched', 'grand_total', 'invoice_status', 'payment_status')
    list_filter = ('invoice_status', 'payment_status')
    search_fields = ('reference_no', 'customer__name')
    inlines = [SaleItemLineInline]


class PaymentAllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 1
    fk_name = 'payment'

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('reference_no', 'company', 'payment_type', 'party', 'amount', 'date_paid')
    list_filter = ('payment_type', 'method')
    inlines = [PaymentAllocationInline]

@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(admin.ModelAdmin):
    list_display = ('payment', 'sale_invoice', 'purchase_invoice', 'allocated_amount')




class SalesReturnItemLineInline(admin.TabularInline):
    model = SalesReturnItemLine
    extra = 1

@admin.register(SalesReturn)
class SalesReturnAdmin(admin.ModelAdmin):
    list_display = ('reference_no', 'company', 'customer', 'date_returned', 'grand_total')
    inlines = [SalesReturnItemLineInline]

@admin.register(SpoilageLoss)
class SpoilageLossAdmin(admin.ModelAdmin):
    list_display = ('reference_no', 'company', 'item', 'warehouse', 'quantity', 'reason', 'total_loss_value', 'date_reported')