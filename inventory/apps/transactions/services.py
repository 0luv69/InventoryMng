from django.db import transaction, models
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.db.models import F
from apps.inventory.models import StockBatch, StockMovement
from apps.catalog.models import Item
from apps.core.utils import get_vat_rate
class InventoryService:
    """ Handles all stock movements, MAC calculations, and validations """
    @staticmethod
    @transaction.atomic
    def process_purchase_line(line):
        base_qty = line.quantity * line.conversion_factor
        total_cost = line.line_total

        # FIX 1: Lock and snapshot stock BEFORE batch mutation
        item = Item.objects.select_for_update().get(id=line.item_id)
        old_stock_qty = item.total_stock
        old_cost_price = item.cost_price

        # 1. Find or Create StockBatch
        batch, created = StockBatch.objects.get_or_create(
            company=line.company,
            item=line.item,
            warehouse=line.warehouse,
            batch_no=line.batch_no,
            defaults={
                'expiry_date': line.expiry_date,
                'landing_cost': line.cost_price,
                'supplier': line.invoice.supplier,
                'created_by': line.invoice.created_by,
                'quantity': base_qty
            }
        )
        
        if not created:
            # FIX 2: Atomic DB-level increment to prevent race conditions
            StockBatch.objects.filter(pk=batch.pk).update(quantity=F('quantity') + base_qty)

        # 2. Create Stock Movement
        StockMovement.objects.create(
            company=line.company, item=line.item, warehouse=line.warehouse,
            batch_no=line.batch_no, movement_type='purchase', quantity=base_qty,
            reference_model='PurchaseInvoice', reference_id=str(line.invoice_id),
            created_by=line.invoice.created_by
        )

        # 3. Update MAC using old snapshot
        new_stock_qty = old_stock_qty + base_qty
        if new_stock_qty > 0:
            new_stock_value = (old_stock_qty * old_cost_price) + total_cost
            item.cost_price = new_stock_value / new_stock_qty
            item.save(update_fields=['cost_price', 'updated_at'])

    @staticmethod
    @transaction.atomic
    def process_sale_line(line):
        base_qty = line.quantity * line.conversion_factor

        # FIX 3: Lock batches during availability check
        batches = StockBatch.objects.select_for_update().filter(
            company=line.company, item=line.item, warehouse=line.warehouse, quantity__gt=0
        ).order_by('expiry_date', 'created_at')

        available_stock = batches.aggregate(total=models.Sum('quantity'))['total'] or 0
        if base_qty > available_stock:
            raise ValidationError(f"Insufficient stock for {line.item.name}. Available: {available_stock} {line.item.base_unit.short_name}")

        # FEFO Deduction
        qty_to_deduct = base_qty
        assigned_batch = None

        for batch in batches:
            if qty_to_deduct <= 0: break
            
            if batch.quantity >= qty_to_deduct:
                # FIX 2: Atomic DB-level decrement
                StockBatch.objects.filter(pk=batch.pk).update(quantity=F('quantity') - qty_to_deduct)
                assigned_batch = batch.batch_no
                qty_to_deduct = 0
            else:
                qty_to_deduct -= batch.quantity
                assigned_batch = batch.batch_no
                StockBatch.objects.filter(pk=batch.pk).update(quantity=0)

        line.assigned_batch_no = assigned_batch or "N/A"
        line.save(update_fields=['assigned_batch_no'])

        StockMovement.objects.create(
            company=line.company, item=line.item, warehouse=line.warehouse,
            batch_no=assigned_batch, movement_type='sale', quantity=-base_qty,
            reference_model='SaleInvoice', reference_id=str(line.invoice_id),
            created_by=line.invoice.created_by
        )

    @staticmethod
    @transaction.atomic
    def reverse_purchase_line(line):
        base_qty = line.quantity * line.conversion_factor
        try:
            # Use atomic decrement here too
            StockBatch.objects.filter(
                company=line.company, item=line.item, warehouse=line.warehouse, batch_no=line.batch_no
            ).update(quantity=F('quantity') - base_qty)
        except StockBatch.DoesNotExist:
            pass

        StockMovement.objects.create(
            company=line.company, item=line.item, warehouse=line.warehouse,
            batch_no=line.batch_no, movement_type='adjustment', quantity=-base_qty,
            notes=f"Reversal of Purchase Line for Invoice {line.invoice_id}"
        )

    @staticmethod
    @transaction.atomic
    def reverse_sale_line(line):
        base_qty = line.quantity * line.conversion_factor
        try:
            StockBatch.objects.filter(
                company=line.company, item=line.item, warehouse=line.warehouse, batch_no=line.assigned_batch_no
            ).update(quantity=F('quantity') + base_qty)
        except StockBatch.DoesNotExist:
            StockBatch.objects.create(
                company=line.company, item=line.item, warehouse=line.warehouse,
                batch_no=f"RETURN-{line.invoice_id}", quantity=base_qty
            )

        StockMovement.objects.create(
            company=line.company, item=line.item, warehouse=line.warehouse,
            batch_no=line.assigned_batch_no, movement_type='sale_return', quantity=base_qty,
            notes=f"Reversal of Sale Line for Invoice {line.invoice_id}"
        )

    @staticmethod
    def recalculate_invoice_totals(invoice):
        from decimal import Decimal
        subtotal = sum(line.line_total for line in invoice.lines.all())
        
        if invoice.discount_type == 'percentage':
            inv_discount = subtotal * (invoice.discount_amount / 100)
        else:
            inv_discount = invoice.discount_amount
            
        taxable_amount = subtotal - inv_discount
        vat_rate = get_vat_rate(invoice.company)
        vat_multiplier = (vat_rate / Decimal('100')) + Decimal('1')

        if invoice.is_vat_inclusive:
            invoice.subtotal = taxable_amount
            invoice.tax_amount = taxable_amount - (taxable_amount / vat_multiplier)
            invoice.grand_total = taxable_amount
        else:
            invoice.subtotal = taxable_amount
            invoice.tax_amount = taxable_amount * (vat_rate / Decimal('100'))
            invoice.grand_total = taxable_amount + invoice.tax_amount
        
        invoice.save(update_fields=['subtotal', 'tax_amount', 'grand_total', 'updated_at'])

    @staticmethod
    @transaction.atomic
    def process_payment_allocation(allocation):
        payment = allocation.payment
        party = payment.party
        
        if payment.payment_type == 'received':
            party.balance -= allocation.allocated_amount
        else:
            party.balance += allocation.allocated_amount
        
        party.save(update_fields=['balance', 'updated_at'])

        invoice = allocation.sale_invoice or allocation.purchase_invoice
        if invoice:
            total_paid = invoice.allocations.aggregate(total=models.Sum('allocated_amount'))['total'] or 0
            if total_paid >= invoice.grand_total:
                invoice.payment_status = 'paid'
            elif total_paid > 0:
                invoice.payment_status = 'partial'
            else:
                invoice.payment_status = 'unpaid'
            invoice.save(update_fields=['payment_status', 'updated_at'])

    @staticmethod
    @transaction.atomic
    def process_sales_return_line(line):
        """ Handles customer returns. Updates stock and customer balance. """
        base_qty = line.quantity * line.conversion_factor
        
        party = line.return_invoice.customer
        party.balance -= line.line_total
        party.save(update_fields=['balance', 'updated_at'])

        if line.is_spoiled:
            StockMovement.objects.create(
                company=line.company, item=line.item, warehouse=line.warehouse,
                batch_no=line.batch_no, movement_type='spoilage', quantity=-base_qty,
                reference_model='SalesReturn', reference_id=str(line.return_invoice_id)
            )
        else:
            batch, created = StockBatch.objects.get_or_create(
                company=line.company, item=line.item, warehouse=line.warehouse, batch_no=line.batch_no,
                defaults={'landing_cost': line.cost_price}
            )
            if not created:
                StockBatch.objects.filter(pk=batch.pk).update(quantity=F('quantity') + base_qty)

            StockMovement.objects.create(
                company=line.company, item=line.item, warehouse=line.warehouse,
                batch_no=line.batch_no, movement_type='sale_return', quantity=base_qty,
                reference_model='SalesReturn', reference_id=str(line.return_invoice_id)
            )

    @staticmethod
    @transaction.atomic
    def process_spoilage(spoilage):
        """ Deducts stock directly from warehouse due to damage/expiry """
        base_qty = spoilage.quantity
        
        try:
            batch = StockBatch.objects.get(
                company=spoilage.company, item=spoilage.item, 
                warehouse=spoilage.warehouse, batch_no=spoilage.batch_no
            )
            StockBatch.objects.filter(pk=batch.pk).update(quantity=F('quantity') - base_qty)
        except StockBatch.DoesNotExist:
            pass
            
        StockMovement.objects.create(
            company=spoilage.company, item=spoilage.item, warehouse=spoilage.warehouse,
            batch_no=spoilage.batch_no, movement_type='spoilage', quantity=-base_qty,
            reference_model='SpoilageLoss', reference_id=str(spoilage.id)
        )