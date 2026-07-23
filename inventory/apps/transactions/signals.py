from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import PaymentAllocation, PurchaseItemLine, SaleItemLine
from .services import InventoryService

@receiver(post_save, sender=PurchaseItemLine)
def purchase_line_saved(sender, instance, created, **kwargs):
    if instance.invoice.invoice_status == 'finalized':
        InventoryService.process_purchase_line(instance)
        InventoryService.recalculate_invoice_totals(instance.invoice)

@receiver(post_delete, sender=PurchaseItemLine)
def purchase_line_deleted(sender, instance, **kwargs):
    if instance.invoice.invoice_status == 'finalized':
        InventoryService.reverse_purchase_line(instance)
        # We must fetch the invoice from DB again because the line is gone
        from .models import PurchaseInvoice
        try:
            invoice = PurchaseInvoice.objects.get(id=instance.invoice_id)
            InventoryService.recalculate_invoice_totals(invoice)
        except PurchaseInvoice.DoesNotExist:
            pass # Invoice itself was deleted

@receiver(post_save, sender=SaleItemLine)
def sale_line_saved(sender, instance, created, **kwargs):
    if instance.invoice.invoice_status == 'finalized':
        InventoryService.process_sale_line(instance)
        InventoryService.recalculate_invoice_totals(instance.invoice)

@receiver(post_delete, sender=SaleItemLine)
def sale_line_deleted(sender, instance, **kwargs):
    if instance.invoice.invoice_status == 'finalized':
        InventoryService.reverse_sale_line(instance)
        from .models import SaleInvoice
        try:
            invoice = SaleInvoice.objects.get(id=instance.invoice_id)
            InventoryService.recalculate_invoice_totals(invoice)
        except SaleInvoice.DoesNotExist:
            pass


@receiver(post_save, sender=PaymentAllocation)
def allocation_saved(sender, instance, created, **kwargs):
    InventoryService.process_payment_allocation(instance)