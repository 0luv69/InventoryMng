from django.views import View
from datetime import timedelta
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Sum, F, Q, Prefetch
from django.utils import timezone
import json
from django.core.files.storage import default_storage
from django.db import transaction, IntegrityError
from decimal import Decimal, InvalidOperation

from apps.catalog.models import Item, Unit, Category, PriceTier, ItemUOM, ItemPrice
from apps.transactions.models import PurchaseInvoice, PurchaseItemLine, SaleInvoice, SaleItemLine
from apps.parties.models import Party
from apps.inventory.models import Warehouse
from apps.transactions.services import InventoryService
from django.http import JsonResponse

from django.core.exceptions import ValidationError

class BaseAppView(LoginRequiredMixin, View):
    pagination_size = 30
    def get_company(self):
        return self.request.user.profile.company

# --- Main Pages ---
class DashboardView(BaseAppView):
    def get(self, request):
        return render(request, 'frontend/dashboard.html')

class QuickAddCategoryView(BaseAppView):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        if name:
            cat = Category.objects.create(company=self.get_company(), name=name, created_by=request.user)
            return JsonResponse({'id': cat.id, 'name': cat.name})
        return JsonResponse({'error': 'Name required'}, status=400)

class QuickAddUnitView(BaseAppView):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        short = request.POST.get('short_name', '').strip()
        if name and short:
            unit = Unit.objects.create(company=self.get_company(), name=name, short_name=short, created_by=request.user)
            return JsonResponse({'id': unit.id, 'name': unit.name, 'short_name': unit.short_name})
        return JsonResponse({'error': 'Name and Short Name required'}, status=400)

class QuickAddPriceTierView(BaseAppView):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        if name:
            tier = PriceTier.objects.create(company=self.get_company(), name=name, created_by=request.user)
            return JsonResponse({'id': tier.id, 'name': tier.name})
        return JsonResponse({'error': 'Name required'}, status=400)

class SetDefaultTierView(BaseAppView):
    def post(self, request, tier_id):
        company = self.get_company()
        PriceTier.objects.filter(company=company).update(is_default=False)
        tier = get_object_or_404(PriceTier, id=tier_id, company=company)
        tier.is_default = True
        tier.save()
        return JsonResponse({'success': True, 'id': tier.id})

# ==========================================
# ITEMS
# ==========================================
class ItemsView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        default_tier = PriceTier.objects.filter(company=company, is_default=True).first()
        context = {
            'units': Unit.objects.filter(company=company),
            'categories': Category.objects.filter(company=company),
            'price_tiers': PriceTier.objects.filter(company=company), 
            'default_tier_id': default_tier.id if default_tier else None,
        }
        return render(request, 'frontend/items/items.html', context)

class ItemFormView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        item_id = request.GET.get('id')
        is_editable = request.GET.get('editable', '0') == '1'
        item = None
        packaging_json = '[]'

        referenced_unit_ids = set()
        referenced_cat_ids = set()
        referenced_sup_ids = set()

        if item_id:
            item = get_object_or_404(Item, id=item_id, company=company)
            uoms = ItemUOM.objects.filter(item=item, is_deleted=False).select_related('unit')
            prices = ItemPrice.objects.filter(item=item, is_deleted=False).select_related('price_tier', 'unit')
            
            referenced_unit_ids.add(item.base_unit_id)
            referenced_cat_ids.add(item.category_id)
            referenced_sup_ids.add(item.default_supplier_id)

            packaging_data = []
            for uom in uoms:
                referenced_unit_ids.add(uom.unit_id)
                # Fix: Quantize to 2 decimals to avoid float drift
                calc_cost = (item.cost_price * uom.conversion_factor).quantize(Decimal('0.01'))
                packaging_data.append({
                    'unit_id': uom.unit_id,
                    'factor': str(uom.conversion_factor),
                    'barcode': uom.barcode,
                    'cost': str(calc_cost),
                    'prices': {str(p.price_tier_id): str(p.price) for p in prices if p.unit_id == uom.unit_id}
                })
            
            # Add base unit manually at index 0
            packaging_data.insert(0, {
                'unit_id': item.base_unit_id,
                'factor': '1',
                'barcode': item.barcode,
                'cost': str(item.cost_price),
                'prices': {str(p.price_tier_id): str(p.price) for p in prices if p.unit_id == item.base_unit_id}
            })
            packaging_json = json.dumps(packaging_data)

        # Fix: Union in soft-deleted units/categories/suppliers referenced by this item
        units_qs = (Unit.objects.filter(company=company) | Unit.all_objects.filter(id__in=referenced_unit_ids)).distinct().order_by('name')
        cats_qs = (Category.objects.filter(company=company) | Category.all_objects.filter(id__in=referenced_cat_ids)).distinct().order_by('name')
        sups_qs = (Party.objects.filter(company=company, is_supplier=True) | Party.all_objects.filter(id__in=referenced_sup_ids, is_supplier=True)).distinct().order_by('name')
        tiers_qs = PriceTier.objects.filter(company=company)

        context = {
            'item': item,
            'is_editable': is_editable,
            'units': units_qs,
            'categories': cats_qs,
            'suppliers': sups_qs,
            'price_tiers': tiers_qs,
            'packaging_json': packaging_json,
            'recent_categories': json.dumps([{'id': c.id, 'name': c.name} for c in cats_qs.order_by('-created_at')[:4] if not c.is_deleted]),
            'recent_units': json.dumps([{'id': u.id, 'name': u.name} for u in units_qs.order_by('-created_at')[:4] if not u.is_deleted]),
            'recent_suppliers': json.dumps([{'id': s.id, 'name': s.name} for s in sups_qs.order_by('-created_at')[:4] if not s.is_deleted]),
            'unit_map_json': json.dumps({str(u.id): f"{u.name} ({u.short_name})" for u in units_qs}),
            'is_locked': item.is_locked if item else False,
        }
        return render(request, 'frontend/items/_form.html', context)

class ItemsTableView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        items = Item.objects.filter(company=company).select_related('category', 'base_unit').annotate(total_stock_calc=Sum('stock_batches__quantity'))

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

        paginator = Paginator(items, self.pagination_size)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {'items': page_obj.object_list, 'page_obj': page_obj, 'request': request}
        return render(request, 'frontend/items/_table.html', context)


class ItemSaveView(BaseAppView):
    @transaction.atomic
    def post(self, request):
        company = self.get_company()
        item_id = request.POST.get('id')
        
        # 1. Server-side required check for name
        name = request.POST.get('name', '').strip()
        if not name:
            return JsonResponse({"success": False, "message": "Item name is required."}, status=400)
            
        # 2. Parse JSON Payload
        grid_json = request.POST.get('packaging_grid')
        if not grid_json:
            return JsonResponse({"success": False, "message": "Missing packaging data."}, status=400)
        
        try:
            grid_data = json.loads(grid_json)
        except json.JSONDecodeError:
            return JsonResponse({"success": False, "message": "Invalid JSON format."}, status=400)

        if not grid_data or len(grid_data) == 0:
            return JsonResponse({"success": False, "message": "At least Base Unit is required."}, status=400)

        # 3. Validate Base Unit & Lock Status (Prevent str(None) bug)
        base_row = grid_data[0]
        raw_base_unit_id = base_row.get('unit_id')
        if not raw_base_unit_id:
            return JsonResponse({"success": False, "message": "Base Unit is required."}, status=400)
        base_unit_id = str(raw_base_unit_id)

        if item_id:
            item = get_object_or_404(Item, id=item_id, company=company)
            if item.is_locked and str(item.base_unit_id) != base_unit_id:
                return JsonResponse({"success": False, "message": "Base Unit cannot be changed because this item has existing transactions."}, status=400)
        else:
            item = Item(company=company)
            item.created_by = request.user

        # 4. Validate Grid Data In-Memory
        parsed_uoms = []
        parsed_prices = []
        seen_units = set([base_unit_id])
        
        try:
            base_cost = Decimal(str(base_row.get('cost', 0)))
            if base_cost < 0: raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            return JsonResponse({"success": False, "message": "Invalid Base Cost price."}, status=400)

        # Lock check for cost_price
        if item_id and item.is_locked and base_cost != item.cost_price:
            return JsonResponse({"success": False, "message": "Cost price can't be changed once this item has transactions."}, status=400)

        for i, row in enumerate(grid_data[1:], start=1):
            raw_unit_id = row.get('unit_id')
            if not raw_unit_id:
                return JsonResponse({"success": False, "message": f"Row {i} is missing a Unit."}, status=400)
            unit_id = str(raw_unit_id)
            
            if unit_id in seen_units:
                return JsonResponse({"success": False, "message": "Duplicate Unit found in grid."}, status=400)
            seen_units.add(unit_id)

            try:
                factor = Decimal(str(row.get('factor')))
                if factor <= 0: raise ValueError
            except (InvalidOperation, ValueError, TypeError):
                return JsonResponse({"success": False, "message": f"Invalid conversion factor for row {i}."}, status=400)

            parsed_uoms.append({'unit_id': unit_id, 'factor': factor, 'barcode': row.get('barcode', '')})

            for tier_id_str, price_val in row.get('prices', {}).items():
                try:
                    price = Decimal(str(price_val))
                    if price < 0: raise ValueError
                except (InvalidOperation, ValueError, TypeError):
                    return JsonResponse({"success": False, "message": f"Invalid price for unit in row {i}."}, status=400)
                parsed_prices.append({'unit_id': unit_id, 'tier_id': str(tier_id_str), 'price': price})

        for tier_id_str, price_val in base_row.get('prices', {}).items():
            try:
                price = Decimal(str(price_val))
                if price < 0: raise ValueError
            except (InvalidOperation, ValueError, TypeError):
                return JsonResponse({"success": False, "message": "Invalid base unit price."}, status=400)
            parsed_prices.append({'unit_id': base_unit_id, 'tier_id': str(tier_id_str), 'price': price})

        # 5. Multi-Tenancy Validation (Units, Tiers, Category, Supplier)
        valid_unit_ids = set(str(u.id) for u in Unit.objects.filter(company=company, id__in=seen_units).values_list('id', flat=True))
        if not seen_units <= valid_unit_ids:
            return JsonResponse({"success": False, "message": "Invalid unit selected."}, status=400)

        referenced_tier_ids = {p['tier_id'] for p in parsed_prices}
        valid_tier_ids = set(str(t.id) for t in PriceTier.objects.filter(company=company, id__in=referenced_tier_ids).values_list('id', flat=True))
        if not referenced_tier_ids <= valid_tier_ids:
            return JsonResponse({"success": False, "message": "Invalid price tier selected."}, status=400)

        category_id = request.POST.get('category') or None
        if category_id and not Category.objects.filter(company=company, id=category_id).exists():
            return JsonResponse({"success": False, "message": "Invalid category selected."}, status=400)

        supplier_id = request.POST.get('default_supplier') or None
        if supplier_id and not Party.objects.filter(company=company, id=supplier_id, is_supplier=True).exists():
            return JsonResponse({"success": False, "message": "Invalid supplier selected."}, status=400)

        # 6. Barcode Validation (Internal & Cross-Table)
        submitted_barcodes = [b for b in ([base_row.get('barcode','')] + [r.get('barcode','') for r in grid_data[1:]]) if b]
        if len(submitted_barcodes) != len(set(submitted_barcodes)):
            return JsonResponse({"success": False, "message": "Duplicate barcode within this item."}, status=400)

        exclude_id = item.id if item_id else None
        if Item.objects.filter(company=company, barcode__in=submitted_barcodes).exclude(id=exclude_id).exists() or \
           ItemUOM.objects.filter(company=company, barcode__in=submitted_barcodes).exclude(item_id=exclude_id).exists():
            return JsonResponse({"success": False, "message": "One of these barcodes is already used by another item."}, status=400)

        # 7. Mutate Database
        item.name = name
        item.category_id = category_id
        item.base_unit_id = base_unit_id
        item.barcode = base_row.get('barcode', '') or ''
        item.default_supplier_id = supplier_id
        item.status = 'active' if request.POST.get('is_active') == 'on' else 'inactive'
        item.cost_price = base_cost

        # Fix: Use .name instead of .path for storage compatibility
        old_image_name = item.image.name if item.image else None
        clear_image_flag = request.POST.get('clear_image') == '1'
        new_image_uploaded = 'image' in request.FILES
        
        if new_image_uploaded:
            item.image = request.FILES['image']
        elif clear_image_flag and item.image:
            item.image = None

        try:
            item.save()
        except IntegrityError:
            return JsonResponse({"success": False, "message": "An item with this name or barcode already exists."}, status=400)
        
        item.uom_conversions.all().delete()
        for uom in parsed_uoms:
            ItemUOM.objects.create(
                company=company, item=item, unit_id=uom['unit_id'], 
                conversion_factor=uom['factor'], barcode=uom['barcode'], created_by=request.user
            )

        item.prices.all().delete()
        for price in parsed_prices:
            ItemPrice.objects.create(
                company=company, item=item, price_tier_id=price['tier_id'], 
                unit_id=price['unit_id'], price=price['price'], created_by=request.user
            )

        new_image_name = item.image.name if item.image else None
        if old_image_name and old_image_name != new_image_name:
            def delete_old_file():
                if default_storage.exists(old_image_name):
                    default_storage.delete(old_image_name)
            transaction.on_commit(delete_old_file)
        
        items = Item.objects.filter(company=company).select_related('category', 'base_unit').annotate(total_stock_calc=Sum('stock_batches__quantity')).order_by('-created_at')
        paginator = Paginator(items, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/items/_table.html', {'items': page_obj.object_list, 'page_obj': page_obj, 'request': request})

class ItemDeleteView(BaseAppView):
    def post(self, request, item_id):
        company = self.get_company()
        item = get_object_or_404(Item, id=item_id, company=company)
        
        reason = request.POST.get('delete_reason', 'No reason provided')
        
        item.is_deleted = True
        item.delete_reason = reason
        item.save()
        
        items = Item.objects.filter(company=company).select_related('category', 'base_unit').annotate(total_stock_calc=Sum('stock_batches__quantity')).order_by('-created_at')
        paginator = Paginator(items, self.pagination_size)
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
            'suppliers': Party.objects.filter(company=company, is_supplier=True, is_deleted=False),
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

        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {
            'invoices': page_obj.object_list,
            'page_obj': page_obj,
            'request': request,
            'suppliers': Party.objects.filter(company=company, is_supplier=True, is_deleted=False),
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
                'cost_price': str((l.cost_price * Decimal('1.13')).quantize(Decimal('0.01'))) if invoice.is_vat_inclusive else str(l.cost_price),
                'batch_no': l.batch_no or '',
                'expiry_date': l.expiry_date.strftime('%Y-%m-%d') if l.expiry_date else ''
            } for l in invoice.lines.all()]
            lines_json = json.dumps(lines_list, cls=DjangoJSONEncoder)

        next_ref = ''
        if not invoice:
            prefix = "PUR-"
            last_inv = PurchaseInvoice.objects.filter(company=company).order_by('-reference_no').first()
            if last_inv:
                try: num = int(last_inv.reference_no.split('-')[1]) + 1
                except: num = 1
            else: num = 1

            next_ref = f"{prefix}{num:04d}"
            while PurchaseInvoice.objects.filter(company=company, reference_no=next_ref).exists():
                num += 1
                next_ref = f"{prefix}{num:04d}"

        suppliers = Party.objects.filter(company=company, is_supplier=True, is_deleted=False)
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
    @transaction.atomic
    def post(self, request):
        company = self.get_company()
        invoice_id = request.POST.get('id')
        
        if invoice_id:
            return JsonResponse({"success": False, "message": "Editing existing invoices is disabled. Please void the invoice and create a new one."}, status=400)
            
        invoice = PurchaseInvoice(company=company)
            
        invoice.supplier_id = request.POST.get('supplier')
        invoice.date_received = request.POST.get('date_received')
        invoice.reference_no = request.POST.get('reference_no')
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

        items_dict = {i.id: i for i in Item.objects.filter(id__in=item_ids, company=company)}

        for i in range(len(item_ids)):
            if item_ids[i]:
                item = items_dict.get(int(item_ids[i]))
                if not item: continue
                
                try: qty_val = Decimal(qtys[i])
                except: qty_val = Decimal('0')
                
                try: gross_cost = Decimal(costs[i])
                except: gross_cost = Decimal('0')

                if invoice.is_vat_inclusive:
                    net_cost = (gross_cost / Decimal('1.13')).quantize(Decimal('0.01'))
                else:
                    net_cost = gross_cost

                batch_no = batches[i].strip() if batches[i] else ''
                if not batch_no:
                    batch_no = f"AUTO-{invoice.reference_no}-B{i+1}"

                PurchaseItemLine.objects.create(
                    company=company, invoice=invoice, item=item, created_by=request.user,
                    warehouse_id=warehouse_id, unit=item.base_unit, conversion_factor=Decimal('1.00'),
                    quantity=qty_val, cost_price=net_cost, batch_no=batch_no, expiry_date=expiries[i] or None
                )
        
        invoices = PurchaseInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_received')
        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_in/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'suppliers': Party.objects.filter(company=company, is_supplier=True, is_deleted=False)})

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
        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_in/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'suppliers': Party.objects.filter(company=company, is_supplier=True, is_deleted=False)})

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
            'customers': Party.objects.filter(company=company, is_customer=True, is_deleted=False),
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

        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {
            'invoices': page_obj.object_list,
            'page_obj': page_obj,
            'request': request,
            'customers': Party.objects.filter(company=company, is_customer=True, is_deleted=False),
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
            lines_list = [{'item_id': l.item_id, 'item_name': l.item.name, 'qty': str(l.quantity), 'selling_price': str(l.selling_price)} for l in invoice.lines.all()]
            lines_json = json.dumps(lines_list)

        if not invoice:
            prefix = "SAL-"
            last_inv = SaleInvoice.objects.filter(company=company).order_by('-reference_no').first()
            if last_inv:
                try: num = int(last_inv.reference_no.split('-')[1]) + 1
                except: num = 1
            else: num = 1

            next_ref = f"{prefix}{num:04d}"
            while SaleInvoice.objects.filter(company=company, reference_no=next_ref).exists():
                num += 1
                next_ref = f"{prefix}{num:04d}"

        customers = Party.objects.filter(company=company, is_customer=True, is_deleted=False)
        warehouses = Warehouse.objects.filter(company=company, is_active=True)
        
        default_tier = PriceTier.objects.filter(company=company, is_default=True).first()
        
        price_qs = ItemPrice.objects.filter(price_tier=default_tier) if default_tier else ItemPrice.objects.all()
        items_qs = Item.objects.filter(company=company, status='active').select_related('category', 'base_unit').prefetch_related(
            Prefetch('prices', queryset=price_qs, to_attr='default_prices')
        )
        
        items_list = []
        for i in items_qs:
            default_sell = str(i.default_prices[0].price) if hasattr(i, 'default_prices') and i.default_prices else str(i.cost_price * Decimal('1.20'))
            items_list.append({
                'id': i.id, 'name': i.name, 'category_id': i.category_id,
                'category_name': i.category.name if i.category else 'Uncategorized',
                'selling_price': default_sell, 'stock': str(i.total_stock)
            })

        context = {
            'invoice': invoice, 'customers': customers, 'warehouses': warehouses,
            'today_str': timezone.now().date().strftime('%Y-%m-%d'),
            'categories': Category.objects.filter(company=company),
            'items_json': json.dumps(items_list), 'lines_json': lines_json,
            'next_ref': next_ref, 'is_vat_inclusive': invoice.is_vat_inclusive if invoice else False,
        }
        return render(request, 'frontend/goods_out/_form.html', context)

class GoodsOutSaveView(BaseAppView):
    def post(self, request):
        company = self.get_company()
        invoice_id = request.POST.get('id')
        
        if invoice_id:
            return JsonResponse({"success": False, "message": "Editing existing sales is disabled. Please void and create a new one."}, status=400)

        grand_total = Decimal('0')
        customer_id = request.POST.get('customer')
        if not customer_id:
            return JsonResponse({"success": False, "message": "Please select a customer."}, status=400)
        customer = Party.objects.get(id=customer_id, company=company)
        
        if customer and customer.credit_limit > 0:
            qtys = request.POST.getlist('qty[]')
            prices = request.POST.getlist('selling_price[]')
            is_vat_inclusive = request.POST.get('is_vat_inclusive') == 'true'

            subtotal = sum(Decimal(q) * Decimal(p) for q, p in zip(qtys, prices))

            if is_vat_inclusive:
                grand_total = subtotal
            else:
                grand_total = subtotal * Decimal('1.13')
            
            if customer.balance + grand_total > customer.credit_limit:
                return JsonResponse({"success": False, "message": f"Credit Limit Exceeded! Limit: Rs. {customer.credit_limit}, Current Balance: Rs. {customer.balance}."}, status=400)

        try:
            with transaction.atomic():
                invoice = SaleInvoice(company=company)
                invoice.customer_id = customer_id
                invoice.date_dispatched = request.POST.get('date_dispatched')
                invoice.reference_no = request.POST.get('reference_no')
                invoice.is_vat_inclusive = request.POST.get('is_vat_inclusive') == 'true'
                invoice.invoice_status = 'finalized'
                invoice.payment_status = 'unpaid'
                invoice.save()

                warehouse_id = request.POST.get('warehouse')
                
                item_ids = request.POST.getlist('item_id[]')
                qtys = request.POST.getlist('qty[]')
                prices = request.POST.getlist('selling_price[]')

                items_dict = {i.id: i for i in Item.objects.filter(id__in=item_ids, company=company)}

                for i in range(len(item_ids)):
                    if item_ids[i]:
                        item = items_dict.get(int(item_ids[i]))
                        if not item: continue
                        
                        try: qty_val = Decimal(qtys[i])
                        except: qty_val = Decimal('0')
                        
                        try: gross_price = Decimal(prices[i])
                        except: gross_price = Decimal('0')

                        SaleItemLine.objects.create(
                            company=company, invoice=invoice, created_by=request.user,
                            item=item, warehouse_id=warehouse_id, unit=item.base_unit,
                            conversion_factor=Decimal('1.00'), quantity=qty_val, selling_price=gross_price,
                        )
        except ValidationError as e:
            return JsonResponse({"success": False, "message": e.messages[0]}, status=400)
        except Exception as e:
            return JsonResponse({"success": False, "message": f"An unexpected error occurred: {str(e)}"}, status=400)
        
        invoices = SaleInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_dispatched')
        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_out/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'customers': Party.objects.filter(company=company, is_customer=True, is_deleted=False)})

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
        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_out/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'customers': Party.objects.filter(company=company, is_customer=True, is_deleted=False)})

class SpoilageView(BaseAppView):
    template_name = "frontend/spoilage.html"

class PaymentsView(BaseAppView):
    template_name = "frontend/payments.html"

class ReportsView(BaseAppView):
    template_name = "frontend/reports.html"

class ProfileView(BaseAppView):
    template_name = "frontend/profile.html"