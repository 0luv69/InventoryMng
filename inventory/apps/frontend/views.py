from django.views import View
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Sum, F
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import redirect

from apps.catalog.models import Item, Unit, Category
from apps.transactions.models import PurchaseInvoice, PurchaseItemLine
from apps.parties.models import Party
from apps.inventory.models import Warehouse
from apps.catalog.models import Item, ItemUOM
import json
from django.db.models import Q
from django.utils import timezone

class BaseAppView(LoginRequiredMixin, View):
    def get_company(self):
        return self.request.user.profile.company


# --- Main Pages ---
class DashboardView(BaseAppView):
    def get(self, request):
        return render(request, 'frontend/dashboard.html')

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


    # --- Main Page ---
class ItemsView(BaseAppView):
    def get(self, request):
        context = {
            'units': Unit.objects.filter(company=self.get_company()),
            'categories': Category.objects.filter(company=self.get_company()),
        }
        return render(request, 'frontend/items/items.html', context)

# --- HTMX Table View ---
class ItemsTableView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        
        # Annotate total_stock so we can sort by it in the database
        items = Item.objects.filter(company=company, is_removed=False).annotate(
            total_stock_calc=Sum('stock_batches__quantity')
        )

        # 1. Search
        search = request.GET.get('search', '')
        if search:
            items = items.filter(name__icontains=search)

        # 2. Filters
        category_id = request.GET.get('category', '')
        if category_id:
            items = items.filter(category_id=category_id)

        unit_id = request.GET.get('unit', '')
        if unit_id:
            items = items.filter(base_unit_id=unit_id)

        status = request.GET.get('status', '')
        if status:
            items = items.filter(status=status)

        # 3. Sorting
        sort = request.GET.get('sort', 'created_at')
        order = request.GET.get('order', 'desc')
        # Added 'total_stock_calc' to valid sorts
        valid_sorts = ['name', 'cost_price', 'created_at', 'total_stock_calc']
        if sort in valid_sorts:
            items = items.order_by(f"{'-' if order == 'desc' else ''}{sort}")
        else:
            items = items.order_by('-created_at')

        # 4. Pagination
        page_num = request.GET.get('page', 1)
        paginator = Paginator(items, 10)
        page_obj = paginator.get_page(page_num)

        context = {
            'items': page_obj.object_list,
            'page_obj': page_obj,
            'request': request,
        }
        return render(request, 'frontend/items/_table.html', context)

# --- Save View ---
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
        
        items = Item.objects.filter(company=company, is_removed=False).annotate(
            total_stock_calc=Sum('stock_batches__quantity')
        ).order_by('-created_at')
        paginator = Paginator(items, 10)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/items/_table.html', {'items': page_obj.object_list, 'page_obj': page_obj, 'request': request})

# --- NEW: Delete View ---
class ItemDeleteView(BaseAppView):
    def post(self, request, item_id):
        company = self.get_company()
        item = get_object_or_404(Item, id=item_id, company=company)
        
        # Soft delete
        item.is_removed = True
        item.status = 'inactive'
        item.save()
        
        # Return updated table
        items = Item.objects.filter(company=company, is_removed=False).annotate(
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
        return render(request, 'frontend/goods_in/goods_in.html')

class GoodsInTableView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        invoices = PurchaseInvoice.objects.filter(company=company, invoice_status='finalized').order_by('-date_received')

        search = request.GET.get('search', '')
        if search:
            invoices = invoices.filter(Q(reference_no__icontains=search) | Q(supplier__name__icontains=search))

        paginator = Paginator(invoices, 10)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        return render(request, 'frontend/goods_in/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request})

class GoodsInFormView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        invoice_id = request.GET.get('id')
        invoice = None
        if invoice_id:
            invoice = get_object_or_404(PurchaseInvoice, id=invoice_id, company=company)

        context = {
            'invoice': invoice,
            'suppliers': Party.objects.filter(company=company, is_supplier=True, is_removed=False),
            'warehouses': Warehouse.objects.filter(company=company, is_active=True),
            'today_str': timezone.now().date().strftime('%Y-%m-%d'),
        }
        return render(request, 'frontend/goods_in/_form.html', context)

#  HTMX Item Search Endpoint
class GoodsInItemSearchView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        q = request.GET.get('q', '')
        index = request.GET.get('index', 0)
        
        # Search by Name, Barcode, or Category
        items = Item.objects.filter(
            company=company, 
            status='active'
        ).filter(
            Q(name__icontains=q) | 
            Q(barcode__icontains=q) | 
            Q(category__name__icontains=q)
        )[:10]
        
        return render(request, 'frontend/goods_in/_item_search.html', {'items': items, 'index': index})

# Updated Save View to handle Line Items
class GoodsInSaveView(BaseAppView):
    def post(self, request):
        company = self.get_company()
        invoice_id = request.POST.get('id')
        
        if invoice_id:
            invoice = get_object_or_404(PurchaseInvoice, id=invoice_id, company=company)
            # Clear old lines if editing (Signals will reverse stock automatically)
            invoice.lines.all().delete()
        else:
            invoice = PurchaseInvoice(company=company)
            
        invoice.supplier_id = request.POST.get('supplier')
        invoice.date_received = request.POST.get('date_received')
        invoice.reference_no = request.POST.get('reference_no')
        invoice.invoice_status = 'finalized'
        invoice.payment_status = 'unpaid'
        invoice.save()

        warehouse_id = request.POST.get('warehouse')
        
        # Get arrays from POST data
        item_ids = request.POST.getlist('item_id[]')
        qtys = request.POST.getlist('qty[]')
        costs = request.POST.getlist('cost_price[]')
        batches = request.POST.getlist('batch_no[]')
        expiries = request.POST.getlist('expiry_date[]')

        # Loop and create PurchaseItemLines
        for i in range(len(item_ids)):
            if item_ids[i]:
                item = Item.objects.get(id=item_ids[i], company=company)
                PurchaseItemLine.objects.create(
                    invoice=invoice,
                    item=item,
                    warehouse_id=warehouse_id,
                    unit=item.base_unit, # Default to base unit for now
                    conversion_factor=1,
                    quantity=qtys[i],
                    cost_price=costs[i],
                    batch_no=batches[i] or None,
                    expiry_date=expiries[i] or None
                )
                # Signal automatically fires here to update stock and MAC!
        
        # Return updated table
        invoices = PurchaseInvoice.objects.filter(company=company, invoice_status='finalized').order_by('-date_received')
        paginator = Paginator(invoices, 10)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_in/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request})




class PartiesView(BaseAppView):
    template_name = "frontend/parties.html"

class GoodsOutView(BaseAppView):
    template_name = "frontend/goods_out.html"

class SpoilageView(BaseAppView):
    template_name = "frontend/spoilage.html"

class PaymentsView(BaseAppView):
    template_name = "frontend/payments.html"

class ReportsView(BaseAppView):
    template_name = "frontend/reports.html"

class ProfileView(BaseAppView):
    template_name = "frontend/profile.html"