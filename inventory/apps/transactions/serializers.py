from rest_framework import serializers
from .models import (
    PurchaseInvoice, PurchaseItemLine,
    SaleInvoice, SaleItemLine,
    Payment, PaymentAllocation
)
from apps.catalog.models import Item
from apps.inventory.models import Warehouse
from apps.parties.models import Party

# ==========================================
# 1. PURCHASE INVOICE SERIALIZERS
# ==========================================
class PurchaseItemLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseItemLine
        fields = ['id', 'item', 'warehouse', 'unit', 'quantity', 'conversion_factor', 
                  'cost_price', 'discount_type', 'discount_amount', 'batch_no', 'expiry_date']
        read_only_fields = ['id']

class PurchaseInvoiceSerializer(serializers.ModelSerializer):
    lines = PurchaseItemLineSerializer(many=True)

    class Meta:
        model = PurchaseInvoice
        fields = ['id', 'reference_no', 'supplier', 'date_received', 'invoice_status', 
                  'subtotal', 'discount_type', 'discount_amount', 'tax_amount', 'grand_total', 
                  'notes', 'lines']
        read_only_fields = ['subtotal', 'tax_amount', 'grand_total'] # System calculates these

    def create(self, validated_data):
        lines_data = validated_data.pop('lines')
        
        # 1. Create the Invoice Header
        invoice = PurchaseInvoice.objects.create(**validated_data)
        
        # 2. Create the Line Items (This triggers our signals!)
        for line_data in lines_data:
            PurchaseItemLine.objects.create(invoice=invoice, **line_data)
            
        # 3. Refresh to get the auto-calculated totals from our signals
        invoice.refresh_from_db()
        return invoice

    def update(self, instance, validated_data):
        lines_data = validated_data.pop('lines', None)
        
        # Update header fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if lines_data is not None:
            # Delete old lines (triggers reverse stock signals)
            instance.lines.all().delete()
            # Create new lines (triggers stock deduction signals)
            for line_data in lines_data:
                PurchaseItemLine.objects.create(invoice=instance, **line_data)
                
        instance.refresh_from_db()
        return instance


# ==========================================
# 2. SALE INVOICE SERIALIZERS
# ==========================================
class SaleItemLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleItemLine
        fields = ['id', 'item', 'warehouse', 'unit', 'quantity', 'conversion_factor', 
                  'selling_price', 'discount_type', 'discount_amount']
        read_only_fields = ['id', 'assigned_batch_no']

class SaleInvoiceSerializer(serializers.ModelSerializer):
    lines = SaleItemLineSerializer(many=True)

    class Meta:
        model = SaleInvoice
        fields = ['id', 'reference_no', 'customer', 'date_dispatched', 'invoice_status',
                  'subtotal', 'discount_type', 'discount_amount', 'tax_amount', 'grand_total',
                  'notes', 'lines']
        read_only_fields = ['subtotal', 'tax_amount', 'grand_total']

    def create(self, validated_data):
        lines_data = validated_data.pop('lines')
        invoice = SaleInvoice.objects.create(**validated_data)
        
        for line_data in lines_data:
            # This triggers the FEFO logic, MAC deduction, and Strict Negative Stock check!
            SaleItemLine.objects.create(invoice=invoice, **line_data)
            
        invoice.refresh_from_db()
        return invoice

    def update(self, instance, validated_data):
        lines_data = validated_data.pop('lines', None)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                SaleItemLine.objects.create(invoice=instance, **line_data)
                
        instance.refresh_from_db()
        return instance


# ==========================================
# 3. PAYMENT SERIALIZERS
# ==========================================
class PaymentAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAllocation
        fields = ['id', 'sale_invoice', 'purchase_invoice', 'allocated_amount']

class PaymentSerializer(serializers.ModelSerializer):
    allocations = PaymentAllocationSerializer(many=True, required=False)

    class Meta:
        model = Payment
        fields = ['id', 'reference_no', 'payment_type', 'party', 'amount', 'date_paid', 
                  'method', 'notes', 'allocations']
        read_only_fields = ['id']

    def create(self, validated_data):
        allocations_data = validated_data.pop('allocations', [])
        payment = Payment.objects.create(**validated_data)
        
        for alloc_data in allocations_data:
            PaymentAllocation.objects.create(payment=payment, **alloc_data)
            
        return payment