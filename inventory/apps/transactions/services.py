# transaction.services

from django.db import transaction, models
from django.core.exceptions import ValidationError
from django.db.models import F
from apps.inventory.models import StockBatch, StockMovement
from .models import PurchaseItemLine, SaleItemLine, SaleItemLineBatch
from apps.catalog.models import Item
from apps.core.utils import get_vat_rate
from decimal import Decimal, ROUND_HALF_UP
from datetime import date

TWO_PLACES = Decimal('0.01')
RUPEE = Decimal('1')


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

        batches = list(StockBatch.objects.select_for_update().filter(
            company=line.company, item=line.item, warehouse=line.warehouse, quantity__gt=0
        ).order_by('created_at'))
        batches.sort(key=lambda b: (b.expiry_date is None, b.expiry_date or date.max))

        available_stock = sum(b.quantity for b in batches)
        if base_qty > available_stock:
            raise ValidationError(f"Insufficient stock for {line.item.name}. Available: {available_stock} {line.item.base_unit.short_name}")

        qty_to_deduct = base_qty
        assigned_batches_count = 0

        for batch in batches:
            if qty_to_deduct <= 0: break
            
            if batch.quantity >= qty_to_deduct:
                deducted_qty = qty_to_deduct
                StockBatch.objects.filter(pk=batch.pk).update(quantity=F('quantity') - deducted_qty)
                qty_to_deduct = 0
            else:
                deducted_qty = batch.quantity
                qty_to_deduct -= batch.quantity
                StockBatch.objects.filter(pk=batch.pk).update(quantity=0)

            # Record the exact allocation (added created_by)
            SaleItemLineBatch.objects.create(
                company=line.company,
                sale_line=line,
                stock_batch=batch,
                quantity=deducted_qty,
                created_by=line.invoice.created_by
            )

            # Create a StockMovement PER BATCH touched
            StockMovement.objects.create(
                company=line.company, item=line.item, warehouse=line.warehouse, batch_no=batch.batch_no,
                movement_type='sale', quantity=-deducted_qty, reference_model='SaleInvoice',
                reference_id=str(line.invoice_id), created_by=line.invoice.created_by
            )

            assigned_batches_count += 1

        # Clean up legacy field for UI display
        line.assigned_batch_no = "MULTI" if assigned_batches_count > 1 else (batch.batch_no if assigned_batches_count == 1 else "N/A")
        line.save(update_fields=['assigned_batch_no'])

    @staticmethod
    @transaction.atomic
    def reverse_purchase_line(line):
        base_qty = line.quantity * line.conversion_factor

        updated = StockBatch.objects.filter(
            company=line.company, item=line.item, warehouse=line.warehouse, batch_no=line.batch_no
        ).update(quantity=F('quantity') - base_qty)
        
        if not updated:
            # Fallback if the batch was hard-deleted somehow (pre-flight makes this near-impossible)
            StockBatch.objects.create(
                company=line.company, item=line.item, warehouse=line.warehouse,
                batch_no=line.batch_no or f"ORPHAN-{line.invoice_id}-{line.id}",  # never blank
                quantity=-base_qty # Negative stock to flag the anomaly
            )

        StockMovement.objects.create(
            company=line.company, item=line.item, warehouse=line.warehouse,
            batch_no=line.batch_no, movement_type='adjustment', quantity=-base_qty,
            reference_model='PurchaseInvoice', reference_id=str(line.invoice_id),
            notes=f"Reversal of Purchase Line for Invoice {line.invoice_id}"
        )

 
    @staticmethod
    @transaction.atomic
    def recompute_mac(item):
        """
        Rebuilds moving-average cost from live batch data (qty > 0).
        Called after voids so cost_price self-heals to batch reality.
        """
        agg = StockBatch.objects.filter(item=item, quantity__gt=0).aggregate(
            qty=models.Sum('quantity'),
            value=models.Sum(models.F('quantity') * models.F('landing_cost')),
        )
        if not agg['qty']:
            return  # No live stock left: keep last known cost, don't zero it
        item.cost_price = (agg['value'] / agg['qty']).quantize(Decimal('0.01'), ROUND_HALF_UP)
        item.save(update_fields=['cost_price', 'updated_at'])

    @staticmethod
    @transaction.atomic
    def reverse_sale_line(line):
        # Query the allocation table instead of trusting a single batch string
        allocations = SaleItemLineBatch.objects.filter(sale_line=line).select_related('stock_batch')
        
        for alloc in allocations:
            # Restore the exact quantity to the exact batch
            StockBatch.objects.filter(pk=alloc.stock_batch_id).update(quantity=F('quantity') + alloc.quantity)
            
            # Create a reversal movement for this specific batch
            StockMovement.objects.create(
                company=line.company, item=line.item, warehouse=line.warehouse, 
                batch_no=alloc.stock_batch.batch_no,
                movement_type='sale_return', quantity=alloc.quantity, 
                reference_model='SaleInvoice',
                reference_id=str(line.invoice_id),
                notes=f"Reversal of Sale Line for Invoice {line.invoice_id}",
                created_by=line.invoice.created_by
            )
            
            # Delete the allocation record since the reversal is complete
            alloc.delete()

    @staticmethod
    @transaction.atomic
    def delete_sale_line(line):
        """ Explicit wrapper to safely reverse and delete a sale line.
        Required because SaleItemLineBatch.sale_line is PROTECT. """
        InventoryService.reverse_sale_line(line)
        line.delete()

    @staticmethod
    def recalculate_invoice_totals(invoice):
        """
            All stored figures are NET of VAT. Works for Purchase and Sale invoices.
            Lines' line_total must already be net (views net prices & fixed discounts
            for VATable lines before storing). No intermediate rounding.
        """
        vat_rate = get_vat_rate(invoice.company)
        lines = list(invoice.lines.all())

        net_subtotal = sum((l.line_total for l in lines), Decimal('0'))

        if invoice.discount_type == 'percentage':
            pct = min(invoice.discount_amount, Decimal('100'))
            net_discount = net_subtotal * (pct / Decimal('100'))
        else:
            net_discount = invoice.discount_amount  # view already netted if inclusive

        net_discount = min(net_discount, net_subtotal)          # defensive clamp
        net_after_discount = net_subtotal - net_discount

        # Proportional VATable share — mixed exempt/VATable bills handled automatically
        vatable_net = sum((l.line_total for l in lines if l.is_vat_applicable), Decimal('0'))
        vatable_after_discount = (vatable_net * (net_after_discount / net_subtotal)
                                if net_subtotal > 0 else Decimal('0'))

        tax_unrounded = vatable_after_discount * (vat_rate / Decimal('100'))

        taxable = net_after_discount.quantize(TWO_PLACES, ROUND_HALF_UP)
        tax = tax_unrounded.quantize(TWO_PLACES, ROUND_HALF_UP)

        grand_unrounded = net_after_discount + tax_unrounded
        if invoice.round_off_enabled:
            invoice.grand_total = grand_unrounded.quantize(RUPEE, ROUND_HALF_UP)
        else:
            invoice.grand_total = grand_unrounded.quantize(TWO_PLACES, ROUND_HALF_UP)

        # Absorbs both deliberate rounding AND residual paisa rounding:
        invoice.round_off = invoice.grand_total - (taxable + tax)
        invoice.subtotal = net_subtotal.quantize(TWO_PLACES, ROUND_HALF_UP)
        invoice.tax_amount = tax
        invoice.save(update_fields=['subtotal', 'tax_amount', 'grand_total',
                                    'round_off', 'updated_at'])



   

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

    @staticmethod
    @transaction.atomic
    def apply_invoice_to_party_balance(invoice, party_field, sign):
        """
        Locks the party row and atomically adjusts balance.
        sign=+1 for Sale (customer owes more), sign=-1 for Purchase (we owe supplier more,
        i.e. balance moves negative per the documented convention).
        """
        from apps.parties.models import Party
        party = Party.objects.select_for_update().get(pk=getattr(invoice, f"{party_field}_id"))
        Party.objects.filter(pk=party.pk).update(
            balance=F('balance') + (sign * invoice.grand_total)
        )

    @staticmethod
    @transaction.atomic
    def reverse_invoice_on_party_balance(invoice, party_field, sign):
        """
        Reverses the balance adjustment when an invoice is voided.
        sign=+1 for Sale (decreases customer balance), sign=-1 for Purchase (increases supplier balance).
        """
        from apps.parties.models import Party
        party_id = getattr(invoice, f"{party_field}_id")
        if party_id:
            Party.objects.select_for_update().filter(pk=party_id).update(
                balance=F('balance') - (sign * invoice.grand_total)
            )