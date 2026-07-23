from django.db import transaction, models
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.inventory.models import StockBatch, StockMovement
from apps.catalog.models import Item

class InventoryService:
    """ Handles all stock movements, MAC calculations, and validations """

    @staticmethod
    @transaction.atomic
    def process_purchase_line(line):
        """ Called when a PurchaseItemLine is saved. Adds stock and updates MAC. """
        base_qty = line.quantity * line.conversion_factor
        total_cost = base_qty * line.cost_price

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
                'created_by': line.invoice.created_by
            }
        )
        
        if not created:
            # If batch already exists, just add the quantity
            batch.quantity += base_qty
            batch.save(update_fields=['quantity', 'updated_at'])

        # 2. Create Stock Movement (Audit Trail)
        StockMovement.objects.create(
            company=line.company,
            item=line.item,
            warehouse=line.warehouse,
            batch_no=line.batch_no,
            movement_type='purchase',
            quantity=base_qty,
            reference_model='PurchaseInvoice',
            reference_id=str(line.invoice_id),
            created_by=line.invoice.created_by
        )

        # 3. Update Moving Average Cost (MAC) on the Item
        item = Item.objects.select_for_update().get(id=line.item_id)
        current_stock_value = (item.total_stock * item.cost_price)
        new_stock_value = current_stock_value + total_cost
        new_stock_qty = item.total_stock + base_qty
        
        if new_stock_qty > 0:
            item.cost_price = new_stock_value / new_stock_qty
            item.save(update_fields=['cost_price', 'updated_at'])


    @staticmethod
    @transaction.atomic
    def process_sale_line(line):
        """ Called when a SaleItemLine is saved. Deducts stock using FEFO. """
        base_qty = line.quantity * line.conversion_factor

        # 1. Check if enough stock exists (Strict Negative Stock Block)
        available_stock = StockBatch.objects.filter(
            item=line.item, 
            warehouse=line.warehouse
        ).aggregate(total=models.Sum('quantity'))['total'] or 0

        if base_qty > available_stock:
            raise ValidationError(f"Insufficient stock for {line.item.name}. Available: {available_stock} {line.item.base_unit.short_name}")

        # 2. FEFO Deduction (First Expired, First Out)
        batches = StockBatch.objects.filter(
            item=line.item, 
            warehouse=line.warehouse, 
            quantity__gt=0
        ).order_by('expiry_date', 'created_at') # Earliest expiry first

        qty_to_deduct = base_qty
        assigned_batch = None

        for batch in batches:
            if qty_to_deduct <= 0:
                break
                
            if batch.quantity >= qty_to_deduct:
                batch.quantity -= qty_to_deduct
                assigned_batch = batch.batch_no
                batch.save(update_fields=['quantity', 'updated_at'])
                qty_to_deduct = 0
            else:
                # Empty this batch and move to the next
                qty_to_deduct -= batch.quantity
                assigned_batch = batch.batch_no
                batch.quantity = 0
                batch.save(update_fields=['quantity', 'updated_at'])

        # Save the assigned batch back to the invoice line for records
        line.assigned_batch_no = assigned_batch or "N/A"
        line.save(update_fields=['assigned_batch_no'])

        # 3. Create Stock Movement
        StockMovement.objects.create(
            company=line.company,
            item=line.item,
            warehouse=line.warehouse,
            batch_no=assigned_batch,
            movement_type='sale',
            quantity=-base_qty, # NEGATIVE for outgoing
            reference_model='SaleInvoice',
            reference_id=str(line.invoice_id),
            created_by=line.invoice.created_by
        )

    @staticmethod
    @transaction.atomic
    def reverse_purchase_line(line):
        """ Called when a PurchaseItemLine is deleted. Reverses stock. """
        base_qty = line.quantity * line.conversion_factor
        
        # Reverse the batch
        try:
            batch = StockBatch.objects.get(
                company=line.company,
                item=line.item,
                warehouse=line.warehouse,
                batch_no=line.batch_no
            )
            batch.quantity -= base_qty
            batch.save(update_fields=['quantity', 'updated_at'])
        except StockBatch.DoesNotExist:
            pass # Batch might have been deleted manually

        # Reverse Movement Log
        StockMovement.objects.create(
            company=line.company,
            item=line.item,
            warehouse=line.warehouse,
            batch_no=line.batch_no,
            movement_type='adjustment',
            quantity=-base_qty,
            notes=f"Reversal of Purchase Line for Invoice {line.invoice_id}"
        )

    @staticmethod
    @transaction.atomic
    def reverse_sale_line(line):
        """ Called when a SaleItemLine is deleted. Restores stock. """
        base_qty = line.quantity * line.conversion_factor
        
        # We don't know exactly which batches were deducted if multiple were used,
        # but for simple reversal, we add it back to the assigned batch or create a generic one.
        try:
            batch = StockBatch.objects.get(
                company=line.company,
                item=line.item,
                warehouse=line.warehouse,
                batch_no=line.assigned_batch_no
            )
            batch.quantity += base_qty
            batch.save(update_fields=['quantity', 'updated_at'])
        except StockBatch.DoesNotExist:
            # If batch doesn't exist, create a generic return batch
            StockBatch.objects.create(
                company=line.company,
                item=line.item,
                warehouse=line.warehouse,
                batch_no=f"RETURN-{line.invoice_id}",
                quantity=base_qty
            )

        # Reverse Movement Log
        StockMovement.objects.create(
            company=line.company,
            item=line.item,
            warehouse=line.warehouse,
            batch_no=line.assigned_batch_no,
            movement_type='sale_return',
            quantity=base_qty,
            notes=f"Reversal of Sale Line for Invoice {line.invoice_id}"
        )


    @staticmethod
    def recalculate_invoice_totals(invoice):
        """ Recalculates the subtotal, tax, and grand total for an invoice """
        from decimal import Decimal
        
        # Sum all line totals
        subtotal = sum(line.line_total for line in invoice.lines.all())
        
        # Calculate Invoice-Level Discount
        if invoice.discount_type == 'percentage':
            inv_discount = subtotal * (invoice.discount_amount / 100)
        else:
            inv_discount = invoice.discount_amount
            
        taxable_amount = subtotal - inv_discount
        
        # Calculate 13% VAT
        tax_amount = taxable_amount * Decimal('0.13')
        
        # Save to invoice
        invoice.subtotal = subtotal
        invoice.tax_amount = tax_amount
        invoice.grand_total = taxable_amount + tax_amount
        invoice.save(update_fields=['subtotal', 'tax_amount', 'grand_total', 'updated_at'])


    @staticmethod
    @transaction.atomic
    def process_payment_allocation(allocation):
        """ Updates Party balance and Invoice payment status when an allocation is saved """
        payment = allocation.payment
        
        # 1. Update Party Balance
        party = payment.party
        if payment.payment_type == 'received':
            # Customer paid us, so their balance decreases
            party.balance -= allocation.allocated_amount
        else:
            # We paid supplier, so our debt to them decreases
            party.balance += allocation.allocated_amount
        
        party.save(update_fields=['balance', 'updated_at'])

        # 2. Update Invoice Payment Status
        invoice = allocation.sale_invoice or allocation.purchase_invoice
        if invoice:
            # Sum all allocations for this invoice
            total_paid = invoice.allocations.aggregate(
                total=models.Sum('allocated_amount')
            )['total'] or 0
            
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
        
        # 1. Reduce Customer Balance (They get money/credit back)
        party = line.return_invoice.customer
        party.balance -= line.line_total
        party.save(update_fields=['balance', 'updated_at'])

        # 2. Handle Stock
        if line.is_spoiled:
            # Do NOT add back to sellable stock. Just log as spoilage movement.
            StockMovement.objects.create(
                company=line.company, item=line.item, warehouse=line.warehouse,
                batch_no=line.batch_no, movement_type='spoilage', quantity=-base_qty,
                reference_model='SalesReturn', reference_id=str(line.return_invoice_id)
            )
        else:
            # Add back to sellable stock in the specified batch
            batch, created = StockBatch.objects.get_or_create(
                company=line.company, item=line.item, warehouse=line.warehouse, batch_no=line.batch_no,
                defaults={'landing_cost': line.cost_price}
            )
            if not created:
                batch.quantity += base_qty
                batch.save(update_fields=['quantity', 'updated_at'])

            # Log movement
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
        
        # Deduct from batch
        try:
            batch = StockBatch.objects.get(
                company=spoilage.company, item=spoilage.item, 
                warehouse=spoilage.warehouse, batch_no=spoilage.batch_no
            )
            batch.quantity -= base_qty
            batch.save(update_fields=['quantity', 'updated_at'])
        except StockBatch.DoesNotExist:
            pass # Or raise error if strict matching is required
            
        # Log movement
        StockMovement.objects.create(
            company=spoilage.company, item=spoilage.item, warehouse=spoilage.warehouse,
            batch_no=spoilage.batch_no, movement_type='spoilage', quantity=-base_qty,
            reference_model='SpoilageLoss', reference_id=str(spoilage.id)
        )








