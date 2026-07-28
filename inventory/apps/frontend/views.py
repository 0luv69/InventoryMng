from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.views import View
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Sum, F
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.utils import timezone
import json

from django.db import transaction
from apps.catalog.models import Item, Unit, Category
from apps.transactions.models import PurchaseInvoice, PurchaseItemLine, SaleInvoice, SaleItemLine
from apps.parties.models import Party
from apps.inventory.models import Warehouse
from apps.transactions.services import InventoryService
from django.http import JsonResponse

from django.core.exceptions import ValidationError

class BaseAppView(LoginRequiredMixin, View):
    def get_company(self):
        return self.request.user.profile.company

# --- Main Pages ---
class DashboardView(BaseAppView):
    def get(self, request):
        return render(request, 'frontend/dashboard.html')


# ==========================================
# ITEMS
# ==========================================
class ItemFormView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        item_id = request.GET.get('id')
        item = None
        if item_id:
            item = get_object_or_404(Item, id=item_id, company=company)
            
        context = {
            'item': item,
            'units': Unit.objects.filter(company=company),
            'categories': Category.objects.filter(company=company),
        }
        return render(request, 'frontend/items/_form.html', context)

class ItemsView(BaseAppView):
    def get(self, request):
        context = {
            'units': Unit.objects.filter(company=self.get_company()),
            'categories': Category.objects.filter(company=self.get_company()),
        }
        return render(request, 'frontend/items/items.html', context)
class ItemsTableView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        
        # CHANGED: exclude(status='deleted') instead of is_removed=False
        items = Item.objects.filter(company=company).exclude(status='deleted').annotate(
            total_stock_calc=Sum('stock_batches__quantity')
        )

        search = request.GET.get('search', '')
        if search:
            items = items.filter(name__icontains=search)

        category_id = request.GET.get('category', '')
        if category_id:
            items = items.filter(category_id=category_id)

        unit_id = request.GET.get('unit', '')
        if unit_id:
            items = items.filter(base_unit_id=unit_id)

        status = request.GET.get('status', '')
        if status:
            items = items.filter(status=status)

        sort = request.GET.get('sort', 'created_at')
        order = request.GET.get('order', 'desc')
        valid_sorts = ['name', 'cost_price', 'created_at', 'total_stock_calc']
        if sort in valid_sorts:
            items = items.order_by(f"{'-' if order == 'desc' else ''}{sort}")
        else:
            items = items.order_by('-created_at')

        paginator = Paginator(items, 10)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {
            'items': page_obj.object_list,
            'page_obj': page_obj,
            'request': request,
        }
        return render(request, 'frontend/items/_table.html', context)


# 2. Update ItemSaveView
class ItemSaveView(BaseAppView):
    def post(self, request):
        company = self.get_company()
        item_id = request.POST.get('id')
        
        if item_id:
            item = get_object_or_404(Item, id=item_id, company=company)
        else:
            item = Item(company=company)
            
        item.name = request.POST.get('name')
        item.category_id = request.POST.get('category') or None
        item.base_unit_id = request.POST.get('base_unit')
        item.cost_price = request.POST.get('cost_price') or 0
        item.barcode = request.POST.get('barcode')
        item.status = 'active' if request.POST.get('is_active') == 'on' else 'inactive'
        
        try:
            item.save()
        except Exception:
            pass
        
        # CHANGED: exclude(status='deleted')
        items = Item.objects.filter(company=company).exclude(status='deleted').annotate(
            total_stock_calc=Sum('stock_batches__quantity')
        ).order_by('-created_at')
        paginator = Paginator(items, 10)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/items/_table.html', {'items': page_obj.object_list, 'page_obj': page_obj, 'request': request})


# 3. Update ItemDeleteView
class ItemDeleteView(BaseAppView):
    def post(self, request, item_id):
        company = self.get_company()
        item = get_object_or_404(Item, id=item_id, company=company)
        
        reason = request.POST.get('delete_reason', 'No reason provided')
        
        # CHANGED: Set status to deleted instead of is_removed=True
        item.status = 'deleted'
        item.delete_reason = reason
        item.save()
        
        # CHANGED: exclude(status='deleted')
        items = Item.objects.filter(company=company).exclude(status='deleted').annotate(
            total_stock_calc=Sum('stock_batches__quantity')
        ).order_by('-created_at')
        paginator = Paginator(items, 10)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/items/_table.html', {'items': page_obj.object_list, 'page_obj': page_obj, 'request': request})



# ==========================================
# GOODS IN (PURCHASE INVOICES)
# ==========================================
class GoodsInView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        today = timezone.now().date()
        context = {
            'suppliers': Party.objects.filter(company=company, is_supplier=True, is_removed=False),
            'today_str': today.strftime('%Y-%m-%d'),
            'yesterday_str': (today - timedelta(days=1)).strftime('%Y-%m-%d'),
            'month_start_str': today.replace(day=1).strftime('%Y-%m-%d'),
        }
        return render(request, 'frontend/goods_in/goods_in.html', context)

class GoodsInTableView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        invoices = PurchaseInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_received')

        search = request.GET.get('search', '')
        if search:
            invoices = invoices.filter(Q(reference_no__icontains=search) | Q(supplier__name__icontains=search))

        supplier_id = request.GET.get('supplier', '')
        if supplier_id:
            invoices = invoices.filter(supplier_id=supplier_id)

        status = request.GET.get('status', '')
        if status:
            invoices = invoices.filter(payment_status=status)

        date_from = request.GET.get('date_from', '')
        if date_from:
            invoices = invoices.filter(date_received__gte=date_from)

        date_to = request.GET.get('date_to', '')
        if date_to:
            invoices = invoices.filter(date_received__lte=date_to)

        sort = request.GET.get('sort', 'date_received')
        order = request.GET.get('order', 'desc')
        valid_sorts = ['date_received', 'grand_total', 'payment_status', 'supplier__name']
        if sort in valid_sorts:
            invoices = invoices.order_by(f"{'-' if order == 'desc' else ''}{sort}")
        else:
            invoices = invoices.order_by('-date_received')

        paginator = Paginator(invoices, 10)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {
            'invoices': page_obj.object_list,
            'page_obj': page_obj,
            'request': request,
            'suppliers': Party.objects.filter(company=company, is_supplier=True, is_removed=False),
        }
        return render(request, 'frontend/goods_in/_table.html', context)

class GoodsInFormView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        invoice_id = request.GET.get('id')
        invoice = None
        lines_json = '[]'

        if invoice_id:
            invoice = get_object_or_404(PurchaseInvoice, id=invoice_id, company=company)
            lines_list = [{
                'item_id': l.item_id,
                'item_name': l.item.name,
                'qty': str(l.quantity),
                # Convert net cost back to gross for display if inclusive
                'cost_price': str((l.cost_price * Decimal('1.13')).quantize(Decimal('0.01'))) if invoice.is_vat_inclusive else str(l.cost_price),
                'batch_no': l.batch_no or '',
                'expiry_date': l.expiry_date.strftime('%Y-%m-%d') if l.expiry_date else ''
            } for l in invoice.lines.all()]
            lines_json = json.dumps(lines_list, cls=DjangoJSONEncoder)

        next_ref = ''
        if not invoice:
            last_inv = PurchaseInvoice.objects.filter(company=company).order_by('-id').first()
            next_num = (last_inv.id + 1) if last_inv else 1
            next_ref = f"PUR-{next_num:04d}"

        suppliers = Party.objects.filter(company=company, is_supplier=True, is_removed=False)
        warehouses = Warehouse.objects.filter(company=company, is_active=True)

        items_qs = Item.objects.filter(company=company, status='active').select_related('category', 'base_unit')
        items_list = [{
            'id': i.id,
            'name': i.name,
            'category_id': i.category_id,
            'category_name': i.category.name if i.category else 'Uncategorized',
            'cost_price': str(i.cost_price),
            'stock': str(i.total_stock)
        } for i in items_qs]

        context = {
            'invoice': invoice,
            'suppliers': suppliers,
            'warehouses': warehouses,
            'today_str': timezone.now().date().strftime('%Y-%m-%d'),
            'categories': Category.objects.filter(company=company),
            'items_json': json.dumps(items_list, cls=DjangoJSONEncoder),
            'lines_json': lines_json,
            'next_ref': next_ref,
            'is_vat_inclusive': invoice.is_vat_inclusive if invoice else False,
        }
        return render(request, 'frontend/goods_in/_form.html', context)


class GoodsInSaveView(BaseAppView):
    def post(self, request):
        company = self.get_company()
        invoice_id = request.POST.get('id')
        
        # SECURITY: Completely block editing of existing invoices. 
        # If they made a mistake, they must Void it and create a new one.
        if invoice_id:
            return JsonResponse({"success": False, "message": "Editing existing invoices is disabled. Please void the invoice and create a new one."}, status=400)
            
        # Proceed to create a NEW invoice
        invoice = PurchaseInvoice(company=company)
            
        invoice.supplier_id = request.POST.get('supplier')
        invoice.date_received = request.POST.get('date_received')
        invoice.reference_no = request.POST.get('reference_no')
        
        # Parse 'true'/'false' string from Alpine JS
        invoice.is_vat_inclusive = request.POST.get('is_vat_inclusive') == 'true'
        invoice.invoice_status = 'finalized'
        invoice.payment_status = 'unpaid'
        invoice.save()

        warehouse_id = request.POST.get('warehouse')
        
        item_ids = request.POST.getlist('item_id[]')
        qtys = request.POST.getlist('qty[]')
        costs = request.POST.getlist('cost_price[]')
        batches = request.POST.getlist('batch_no[]')
        expiries = request.POST.getlist('expiry_date[]')

        for i in range(len(item_ids)):
            if item_ids[i]:
                item = Item.objects.get(id=item_ids[i], company=company)
                
                try: qty_val = Decimal(qtys[i])
                except: qty_val = Decimal('0')
                
                try: gross_cost = Decimal(costs[i])
                except: gross_cost = Decimal('0')

                # If VAT inclusive, extract Net Cost before saving to DB
                if invoice.is_vat_inclusive:
                    net_cost = (gross_cost / Decimal('1.13')).quantize(Decimal('0.01'))
                else:
                    net_cost = gross_cost

                PurchaseItemLine.objects.create(
                    invoice=invoice,
                    item=item,
                    warehouse_id=warehouse_id,
                    unit=item.base_unit,
                    conversion_factor=Decimal('1.00'),
                    quantity=qty_val,
                    cost_price=net_cost, # Save NET cost price
                    batch_no=batches[i] or None,
                    expiry_date=expiries[i] or None
                )
        
        # Return updated table
        invoices = PurchaseInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_received')
        paginator = Paginator(invoices, 10)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_in/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'suppliers': Party.objects.filter(company=company, is_supplier=True, is_removed=False)})

class GoodsInVoidView(BaseAppView):
    def post(self, request, invoice_id):
        company = self.get_company()
        invoice = get_object_or_404(PurchaseInvoice, id=invoice_id, company=company)
        reason = request.POST.get('void_reason', 'No reason provided')
        
        for line in invoice.lines.all():
            InventoryService.reverse_purchase_line(line)
        
        invoice.invoice_status = 'void'
        invoice.void_reason = reason
        invoice.save()
        
        invoices = PurchaseInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_received')
        paginator = Paginator(invoices, 10)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_in/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'suppliers': Party.objects.filter(company=company, is_supplier=True, is_removed=False)})

class PartiesView(BaseAppView):
    template_name = "frontend/parties.html"





# ==========================================
# GOODS OUT (SALE INVOICES)
# ==========================================
class GoodsOutView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        today = timezone.now().date()
        context = {
            'customers': Party.objects.filter(company=company, is_customer=True, is_removed=False),
            'today_str': today.strftime('%Y-%m-%d'),
            'yesterday_str': (today - timedelta(days=1)).strftime('%Y-%m-%d'),
            'month_start_str': today.replace(day=1).strftime('%Y-%m-%d'),
        }
        return render(request, 'frontend/goods_out/goods_out.html', context)

class GoodsOutTableView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        invoices = SaleInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_dispatched')

        search = request.GET.get('search', '')
        if search:
            invoices = invoices.filter(Q(reference_no__icontains=search) | Q(customer__name__icontains=search))

        customer_id = request.GET.get('customer', '')
        if customer_id:
            invoices = invoices.filter(customer_id=customer_id)

        status = request.GET.get('status', '')
        if status:
            invoices = invoices.filter(payment_status=status)

        # ADDED: Date Filtering
        date_from = request.GET.get('date_from', '')
        if date_from:
            invoices = invoices.filter(date_dispatched__gte=date_from)

        date_to = request.GET.get('date_to', '')
        if date_to:
            invoices = invoices.filter(date_dispatched__lte=date_to)

        sort = request.GET.get('sort', 'date_dispatched')
        order = request.GET.get('order', 'desc')
        valid_sorts = ['date_dispatched', 'grand_total', 'payment_status', 'customer__name']
        if sort in valid_sorts:
            invoices = invoices.order_by(f"{'-' if order == 'desc' else ''}{sort}")
        else:
            invoices = invoices.order_by('-date_dispatched')

        paginator = Paginator(invoices, 10)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {
            'invoices': page_obj.object_list,
            'page_obj': page_obj,
            'request': request,
            'customers': Party.objects.filter(company=company, is_customer=True, is_removed=False),
        }
        return render(request, 'frontend/goods_out/_table.html', context)


class GoodsOutFormView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        invoice_id = request.GET.get('id')
        invoice = None
        lines_json = '[]'

        if invoice_id:
            invoice = get_object_or_404(SaleInvoice, id=invoice_id, company=company)
            lines_list = [{
                'item_id': l.item_id,
                'item_name': l.item.name,
                'qty': str(l.quantity),
                'selling_price': str(l.selling_price)
            } for l in invoice.lines.all()]
            lines_json = json.dumps(lines_list)

        next_ref = ''
        if not invoice:
            last_inv = SaleInvoice.objects.filter(company=company).order_by('-id').first()
            next_num = (last_inv.id + 1) if last_inv else 1
            next_ref = f"SAL-{next_num:04d}"

        customers = Party.objects.filter(company=company, is_customer=True, is_removed=False)
        warehouses = Warehouse.objects.filter(company=company, is_active=True)

        items_qs = Item.objects.filter(company=company, status='active').select_related('category', 'base_unit')
        items_list = [{
            'id': i.id,
            'name': i.name,
            'category_id': i.category_id,
            'category_name': i.category.name if i.category else 'Uncategorized',
            'selling_price': str(i.cost_price), # Default to cost price, user can change
            'stock': str(i.total_stock)
        } for i in items_qs]

        context = {
            'invoice': invoice,
            'customers': customers,
            'warehouses': warehouses,
            'today_str': timezone.now().date().strftime('%Y-%m-%d'),
            'categories': Category.objects.filter(company=company),
            'items_json': json.dumps(items_list),
            'lines_json': lines_json,
            'next_ref': next_ref,
            'is_vat_inclusive': invoice.is_vat_inclusive if invoice else False,
        }
        return render(request, 'frontend/goods_out/_form.html', context)

class GoodsOutSaveView(BaseAppView):
    def post(self, request):
        company = self.get_company()
        invoice_id = request.POST.get('id')
        
        if invoice_id:
            return JsonResponse({"success": False, "message": "Editing existing sales is disabled. Please void and create a new one."}, status=400)
            
        invoice = SaleInvoice(company=company)
            
        invoice.customer_id = request.POST.get('customer')
        invoice.date_dispatched = request.POST.get('date_dispatched')
        invoice.reference_no = request.POST.get('reference_no')
        invoice.is_vat_inclusive = request.POST.get('is_vat_inclusive') == 'true'
        invoice.invoice_status = 'finalized'
        invoice.payment_status = 'unpaid'
        
        # Check Credit Limit BEFORE saving
        customer = invoice.customer
        if customer and customer.credit_limit > 0:
            new_total = sum(Decimal(q) * Decimal(p) for q, p in zip(request.POST.getlist('qty[]'), request.POST.getlist('selling_price[]')))
            if customer.balance + new_total > customer.credit_limit:
                return JsonResponse({"success": False, "message": f"Credit Limit Exceeded! Limit: Rs. {customer.credit_limit}, Balance: Rs. {customer.balance}."}, status=400)

        warehouse_id = request.POST.get('warehouse')
        item_ids = request.POST.getlist('item_id[]')
        qtys = request.POST.getlist('qty[]')
        prices = request.POST.getlist('selling_price[]')

        try:
            # Wrap in transaction.atomic so if stock fails, the invoice doesn't save
            with transaction.atomic():
                invoice.save()

                for i in range(len(item_ids)):
                    if item_ids[i]:
                        item = Item.objects.get(id=item_ids[i], company=company)
                        
                        try: qty_val = Decimal(qtys[i])
                        except: qty_val = Decimal('0')
                        
                        try: gross_price = Decimal(prices[i])
                        except: gross_price = Decimal('0')

                        if invoice.is_vat_inclusive:
                            net_price = (gross_price / Decimal('1.13')).quantize(Decimal('0.01'))
                        else:
                            net_price = gross_price

                        SaleItemLine.objects.create(
                            invoice=invoice,
                            item=item,
                            warehouse_id=warehouse_id,
                            unit=item.base_unit,
                            conversion_factor=Decimal('1.00'),
                            quantity=qty_val,
                            selling_price=net_price,
                        )
                        # Signal automatically fires here to deduct stock via FEFO!
                        
        except ValidationError as e:
            # This catches the "Insufficient stock" error from our InventoryService!
            return JsonResponse({"success": False, "message": e.messages[0]}, status=400)
        except Exception as e:
            return JsonResponse({"success": False, "message": str(e)}, status=400)
        
        invoices = SaleInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_dispatched')
        paginator = Paginator(invoices, 10)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_out/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'customers': Party.objects.filter(company=company, is_customer=True, is_removed=False)})

class GoodsOutVoidView(BaseAppView):
    def post(self, request, invoice_id):
        company = self.get_company()
        invoice = get_object_or_404(SaleInvoice, id=invoice_id, company=company)
        reason = request.POST.get('void_reason', 'No reason provided')
        
        for line in invoice.lines.all():
            InventoryService.reverse_sale_line(line)
        
        invoice.invoice_status = 'void'
        invoice.void_reason = reason
        invoice.save()
        
        invoices = SaleInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_dispatched')
        paginator = Paginator(invoices, 10)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_out/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'customers': Party.objects.filter(company=company, is_customer=True, is_removed=False)})




class SpoilageView(BaseAppView):
    template_name = "frontend/spoilage.html"

class PaymentsView(BaseAppView):
    template_name = "frontend/payments.html"

class ReportsView(BaseAppView):
    template_name = "frontend/reports.html"

class ProfileView(BaseAppView):
    template_name = "frontend/profile.html"