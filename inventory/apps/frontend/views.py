# frontend.views


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
from django.http import JsonResponse, request

from django.core.exceptions import ValidationError


from apps.core.utils import get_vat_rate

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
    @transaction.atomic
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
                calc_cost = (item.cost_price * uom.conversion_factor).quantize(Decimal('0.01'))
                packaging_data.append({
                    'unit_id': uom.unit_id,
                    'factor': str(uom.conversion_factor),
                    'barcode': uom.barcode,
                    'cost': str(calc_cost),
                    'prices': {str(p.price_tier_id): str(p.price) for p in prices if p.unit_id == uom.unit_id}
                })
            
            packaging_data.insert(0, {
                'unit_id': item.base_unit_id,
                'factor': '1',
                'barcode': item.barcode,
                'cost': str(item.cost_price.quantize(Decimal('0.01'))),
                'prices': {str(p.price_tier_id): str(p.price) for p in prices if p.unit_id == item.base_unit_id}
            })
            packaging_json = json.dumps(packaging_data)

        # Union in soft-deleted units/categories/suppliers referenced by this item
        units_qs = (Unit.objects.filter(company=company) | Unit.all_objects.filter(id__in=referenced_unit_ids)).distinct().order_by('name')
        cats_qs = (Category.objects.filter(company=company) | Category.all_objects.filter(id__in=referenced_cat_ids)).distinct().order_by('name')
        sups_qs = (Party.objects.filter(company=company, is_supplier=True) | Party.all_objects.filter(id__in=referenced_sup_ids, is_supplier=True)).distinct().order_by('name')
        tiers_qs = PriceTier.objects.filter(company=company)
        carton_unit = Unit.objects.filter(company=company, name__iexact='carton').first()



        context = {
            'item': item,
            'is_editable': is_editable,
            'units': units_qs,
            'categories': cats_qs,
            'suppliers': sups_qs,
            'price_tiers': tiers_qs,
            'packaging_json': packaging_json,
            # FIX: Use standard filtered querysets for recent picks so we always get 4 active records
            'recent_categories': json.dumps([{'id': c.id, 'name': c.name} for c in Category.objects.filter(company=company).order_by('-created_at')[:4]]),
            'recent_units': json.dumps([{'id': u.id, 'name': u.name} for u in Unit.objects.filter(company=company).order_by('-created_at')[:4]]),
            'recent_suppliers': json.dumps([{'id': s.id, 'name': s.name} for s in Party.objects.filter(company=company, is_supplier=True).order_by('-created_at')[:4]]),
            'unit_map_json': json.dumps({str(u.id): f"{u.name} ({u.short_name})" for u in units_qs}),
            'is_locked': item.is_locked if item else False,
            'tier_ids_json': json.dumps([t.id for t in tiers_qs]),
            'carton_unit_id': carton_unit.id if carton_unit else '',
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

        # 5. Multi-Tenancy Validation 
        # 5. Multi-Tenancy Validation (FIX: Use all_objects so soft-deleted units don't fail the check)
        valid_unit_ids = set(str(id_) for id_ in Unit.all_objects.filter(company=company, id__in=seen_units).values_list('id', flat=True))
        if not seen_units <= valid_unit_ids:
            return JsonResponse({"success": False, "message": "Invalid unit selected."}, status=400)

        referenced_tier_ids = {p['tier_id'] for p in parsed_prices}
        # FIX: values_list('id', flat=True) yields ints, not objects. Removed .id attribute access.
        valid_tier_ids = set(str(id_) for id_ in PriceTier.all_objects.filter(company=company, id__in=referenced_tier_ids).values_list('id', flat=True))
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

            vat_rate = get_vat_rate(company)
            vat_multiplier = (vat_rate / Decimal('100')) + Decimal('1')

            lines_qs = invoice.lines.select_related('item__base_unit', 'unit').prefetch_related('item__uom_conversions__unit').all()
            
            lines_list = [{
                'item_id': l.item_id,
                'item_name': l.item.name,
                'qty': str(l.quantity),
                'cost_price': str((l.cost_price * vat_multiplier).quantize(Decimal('0.01'))) if invoice.is_vat_inclusive else str(l.cost_price),
                'batch_no': l.batch_no or '',
                'expiry_date': l.expiry_date.strftime('%Y-%m-%d') if l.expiry_date else '',
                'unit_id': l.unit_id,
                'base_unit_id': l.item.base_unit_id,
                'base_unit_name': l.item.base_unit.name,
                'uoms': [{'unit_id': u.unit_id, 'factor': str(u.conversion_factor), 'name': u.unit.name} 
                         for u in l.item.uom_conversions.all()]
            } for l in lines_qs]
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

        items_qs = Item.objects.filter(company=company, status='active').select_related('category', 'base_unit').annotate(total_stock_calc=Sum('stock_batches__quantity'))
        items_list = [{
            'id': i.id,
            'name': i.name,
            'category_id': i.category_id,
            'category_name': i.category.name if i.category else 'Uncategorized',
            'cost_price': str(i.cost_price),
            'base_unit_id': i.base_unit_id,
            'base_unit_name': i.base_unit.name,
            'uoms': [{'unit_id': u.unit_id, 'factor': str(u.conversion_factor), 'name': u.unit.name} for u in i.uom_conversions.all()],
            'stock': str(i.total_stock_calc or 0)
        } for i in items_qs]

        vat_rate = get_vat_rate(company)

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
            'vat_rate': str(vat_rate),
        }
        return render(request, 'frontend/goods_in/_form.html', context)

class GoodsInSaveView(BaseAppView):
    def post(self, request):
        company = self.get_company()
        invoice_id = request.POST.get('id')
        
        if invoice_id:
            return JsonResponse({"success": False, "message": "Editing existing invoices is disabled. Please void the invoice and create a new one."}, status=400)

        # 1. Multi-Tenancy Validation
        supplier_id = request.POST.get('supplier')
        warehouse_id = request.POST.get('warehouse')
        
        if not supplier_id or not Party.objects.filter(id=supplier_id, company=company, is_supplier=True).exists():
            return JsonResponse({"success": False, "message": "Invalid supplier selected."}, status=400)
            
        if not warehouse_id or not Warehouse.objects.filter(id=warehouse_id, company=company, is_active=True).exists():
            return JsonResponse({"success": False, "message": "Invalid warehouse selected."}, status=400)

        # 2. Parse & Validate Lines In-Memory (BEFORE touching DB)
        item_ids = request.POST.getlist('item_id[]')
        qtys = request.POST.getlist('qty[]')
        costs = request.POST.getlist('cost_price[]')
        batches = request.POST.getlist('batch_no[]')
        expiries = request.POST.getlist('expiry_date[]')
        unit_ids = request.POST.getlist('unit_id[]')
        line_discount_types = request.POST.getlist('discount_type[]')     
        line_discount_amounts = request.POST.getlist('discount_amount[]') 

        items_dict = {i.id: i for i in Item.objects.filter(id__in=item_ids, company=company)}
        vat_rate = get_vat_rate(company)
        vat_multiplier = (vat_rate / Decimal('100')) + Decimal('1')

        parsed_lines = []
        try:
            for i in range(len(item_ids)):
                if not item_ids[i]: continue
                item = items_dict.get(int(item_ids[i]))
                if not item:
                    return JsonResponse({"success": False, "message": "Invalid item selected."}, status=400)

                try:
                    qty_val = Decimal(qtys[i])
                    if qty_val <= 0: raise ValueError
                except (InvalidOperation, ValueError, TypeError):
                    return JsonResponse({"success": False, "message": f"Invalid quantity for {item.name}."}, status=400)

                try:
                    gross_cost = Decimal(costs[i])
                    if gross_cost < 0: raise ValueError
                except (InvalidOperation, ValueError, TypeError):
                    return JsonResponse({"success": False, "message": f"Invalid cost price for {item.name}."}, status=400)

                try:
                    unit_id = int(unit_ids[i])
                    if unit_id == item.base_unit_id:
                        conversion_factor = Decimal('1.00')
                    else:
                        uom = ItemUOM.objects.get(item=item, unit_id=unit_id, company=company)
                        conversion_factor = uom.conversion_factor
                except (ValueError, ItemUOM.DoesNotExist):
                    return JsonResponse({"success": False, "message": f"'{item.name}' is not configured for that unit."}, status=400)

                raw_disc_type = line_discount_types[i] if i < len(line_discount_types) else 'fixed'
                line_disc_type = raw_disc_type if raw_disc_type in ('fixed', 'percentage') else 'fixed'

                try:
                    line_disc_amount = Decimal(line_discount_amounts[i] or '0') if i < len(line_discount_amounts) else Decimal('0')
                    if line_disc_amount < 0:
                        raise ValueError
                    if line_disc_type == 'percentage' and line_disc_amount > 100:
                        raise ValueError
                except (InvalidOperation, ValueError, TypeError):
                    return JsonResponse({"success": False, "message": f"Invalid discount for {item.name}."}, status=400)


                batch_no = batches[i].strip() if batches[i] else ''
                if not batch_no:
                    batch_no = f"AUTO-{request.POST.get('reference_no')}-B{i+1}"

                parsed_lines.append({
                    'item': item, 'qty_val': qty_val, 'gross_cost': gross_cost,
                    'batch_no': batch_no, 'expiry_date': expiries[i] or None,
                    'unit_id': unit_id, 'factor': conversion_factor,
                    'discount_type': line_disc_type, 'discount_amount': line_disc_amount,
                })
        except (ValueError, IndexError, TypeError, InvalidOperation):
            return JsonResponse({"success": False, "message": "Invalid data format in invoice lines."}, status=400)


        if not parsed_lines:
            return JsonResponse({"success": False, "message": "At least one item line is required."}, status=400)


        discount_type = request.POST.get('discount_type', 'fixed')
        try:
            discount_amount = Decimal(request.POST.get('discount_amount', '0') or '0').quantize(Decimal('0.01'))
            if discount_amount < 0: raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            return JsonResponse({"success": False, "message": "Invalid discount amount."}, status=400)


        # 3. Mutate DB inside Atomic Block
        try:
            with transaction.atomic():
                invoice = PurchaseInvoice(company=company)
                invoice.supplier_id = supplier_id
                invoice.date_received = request.POST.get('date_received')
                invoice.reference_no = request.POST.get('reference_no')
                invoice.is_vat_inclusive = request.POST.get('is_vat_inclusive') == 'true'
                invoice.invoice_status = 'finalized'
                invoice.payment_status = 'unpaid'
                invoice.discount_type = discount_type
                invoice.discount_amount = discount_amount
                invoice.created_by = request.user  

                try:
                    invoice.full_clean()
                    invoice.save()
                except IntegrityError:
                    raise ValidationError("Invoice with this reference no already exists.")

                for p in parsed_lines:
                    if invoice.is_vat_inclusive:
                        net_cost = (p['gross_cost'] / vat_multiplier).quantize(Decimal('0.01'))
                    else:
                        net_cost = p['gross_cost']


                    line_subtotal_net = (p['qty_val'] * net_cost).quantize(Decimal('0.01'))
                    if p['discount_type'] == 'fixed' and p['discount_amount'] > line_subtotal_net:
                        raise ValidationError(f"Discount exceeds line total for {p['item'].name}.")


                    PurchaseItemLine.objects.create(
                        company=company, invoice=invoice, item=p['item'], created_by=request.user,
                        warehouse_id=warehouse_id, unit_id=p['unit_id'], conversion_factor=p['factor'],
                        quantity=p['qty_val'], cost_price=net_cost, batch_no=p['batch_no'], expiry_date=p['expiry_date'],
                        discount_type=p['discount_type'], discount_amount=p['discount_amount'],
                    )

                InventoryService.recalculate_invoice_totals(invoice)
                invoice.full_clean()

                InventoryService.apply_invoice_to_party_balance(invoice, 'supplier', sign=-1)



        except ValidationError as e:
            return JsonResponse({"success": False, "message": e.messages[0]}, status=400)
        except Exception:
            return JsonResponse({"success": False, "message": "An unexpected server error occurred."}, status=400)
        
        invoices = PurchaseInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_received')
        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_in/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'suppliers': Party.objects.filter(company=company, is_supplier=True, is_deleted=False)})

class GoodsInVoidView(BaseAppView):
    def post(self, request, invoice_id):
        company = self.get_company()
        reason = request.POST.get('void_reason', 'No reason provided')

        try:
            with transaction.atomic():
                invoice = get_object_or_404(
                    PurchaseInvoice.objects.select_for_update(), 
                    id=invoice_id, 
                    company=company
                )
                
                # FIX 2: Idempotency guard - if it's already voided, do nothing and return error
                if invoice.invoice_status != 'finalized':
                    return JsonResponse(
                        {"success": False, "message": "Only finalized invoices can be voided."}, 
                        status=400
                    )

                # Reverse stock
                for line in invoice.lines.all():
                    InventoryService.reverse_purchase_line(line)

                # Reverse AP balance safely
                InventoryService.reverse_invoice_on_party_balance(invoice, 'supplier', sign=-1)

                # Void the invoice
                invoice.invoice_status = 'void'
                invoice.void_reason = reason
                invoice.save()
                
        except Exception as e:
            return JsonResponse({"success": False, "message": "An unexpected server error occurred."}, status=400)
        
        invoices = PurchaseInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_received')
        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_in/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'suppliers': Party.objects.filter(company=company, is_supplier=True, is_deleted=False)})

    

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
        next_ref = ''


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
        if default_tier:
            price_qs = ItemPrice.objects.filter(price_tier=default_tier, unit=F('item__base_unit'))
        else:
            price_qs = ItemPrice.objects.none()

        items_qs = Item.objects.filter(company=company, status='active').select_related('category', 'base_unit').annotate(
            total_stock_calc=Sum('stock_batches__quantity')
        ).prefetch_related(Prefetch('prices', queryset=price_qs, to_attr='default_prices'))
        
        
        items_list = []
        for i in items_qs:
            default_sell = str(i.default_prices[0].price) if hasattr(i, 'default_prices') and i.default_prices else str(i.cost_price * Decimal('1.20'))
            items_list.append({
                'id': i.id, 'name': i.name, 'category_id': i.category_id,
                'category_name': i.category.name if i.category else 'Uncategorized',
                'selling_price': default_sell, 'stock': str(i.total_stock_calc or 0)
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

        customer_id = request.POST.get('customer')
        if not customer_id:
            return JsonResponse({"success": False, "message": "Please select a customer."}, status=400)
        
        try:
            customer = Party.objects.get(id=customer_id, company=company, is_customer=True)
        except Party.DoesNotExist:
            return JsonResponse({"success": False, "message": "Invalid customer selected."}, status=400)


        warehouse_id = request.POST.get('warehouse')
        if not warehouse_id or not Warehouse.objects.filter(id=warehouse_id, company=company, is_active=True).exists():
            return JsonResponse({"success": False, "message": "Invalid warehouse selected."}, status=400)


        item_ids = request.POST.getlist('item_id[]')
        qtys = request.POST.getlist('qty[]')
        prices = request.POST.getlist('selling_price[]')
        items_dict = {i.id: i for i in Item.objects.filter(id__in=item_ids, company=company)}

        # Validate every line in-memory BEFORE touching the DB (mirrors GoodsIn)
        parsed_lines = []
        try:
            for i in range(len(item_ids)):
                if not item_ids[i]:
                    continue
                item = items_dict.get(int(item_ids[i]))
                if not item:
                    return JsonResponse({"success": False, "message": "Invalid item selected."}, status=400)

                try:
                    qty_val = Decimal(qtys[i])
                    if qty_val <= 0: raise ValueError
                except (InvalidOperation, ValueError, TypeError):
                    return JsonResponse({"success": False, "message": f"Invalid quantity for {item.name}."}, status=400)

                try:
                    gross_price = Decimal(prices[i])
                    if gross_price < 0: raise ValueError
                except (InvalidOperation, ValueError, TypeError):
                    return JsonResponse({"success": False, "message": f"Invalid price for {item.name}."}, status=400)

                parsed_lines.append((item, qty_val, gross_price))

        except (ValueError, IndexError, TypeError, InvalidOperation):
            return JsonResponse({"success": False, "message": "Invalid data format in invoice lines."}, status=400)

        if not parsed_lines:
            return JsonResponse({"success": False, "message": "At least one item line is required."}, status=400)


        discount_type = request.POST.get('discount_type', 'fixed')
        try:
            discount_amount = Decimal(request.POST.get('discount_amount', '0') or '0')
            if discount_amount < 0: raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            return JsonResponse({"success": False, "message": "Invalid discount amount."}, status=400)


        try:
            with transaction.atomic():
                invoice = SaleInvoice(company=company)
                invoice.customer_id = customer_id
                invoice.date_dispatched = request.POST.get('date_dispatched')
                invoice.reference_no = request.POST.get('reference_no')
                invoice.is_vat_inclusive = request.POST.get('is_vat_inclusive') == 'true'
                invoice.invoice_status = 'finalized'
                invoice.payment_status = 'unpaid'
                invoice.discount_type = discount_type
                invoice.discount_amount = discount_amount
                invoice.created_by = request.user  # FIX: was missing

                try:
                    invoice.full_clean() # Validate header fields
                    invoice.save()
                except IntegrityError:
                    raise ValidationError("Invoice with this reference no already exists.")


                for item, qty_val, gross_price in parsed_lines:
                    SaleItemLine.objects.create(
                        company=company, invoice=invoice, created_by=request.user,
                        item=item, warehouse_id=warehouse_id, unit=item.base_unit,
                        conversion_factor=Decimal('1.00'), quantity=qty_val, selling_price=gross_price,
                    )

                # Trigger recalculation to get accurate grand_total
                InventoryService.recalculate_invoice_totals(invoice)
                invoice.full_clean()

                # FIX: locked, race-safe balance update — moved out of the view and into
                # the service layer, fetched+locked fresh here rather than pre-atomic-block
                InventoryService.apply_invoice_to_party_balance(invoice, 'customer', sign=+1)

        except ValidationError as e:
            return JsonResponse({"success": False, "message": e.messages[0]}, status=400)
        except Exception as e:
            return JsonResponse({"success": False, "message": "An unexpected server error occurred."}, status=400)
        
        invoices = SaleInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_dispatched')
        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_out/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'customers': Party.objects.filter(company=company, is_customer=True, is_deleted=False)})

class GoodsOutVoidView(BaseAppView):
    def post(self, request, invoice_id):
        company = self.get_company()
        reason = request.POST.get('void_reason', 'No reason provided')
        
        try:
            with transaction.atomic():
                # FIX 1: Lock the invoice row to prevent double-void race conditions
                invoice = get_object_or_404(
                    SaleInvoice.objects.select_for_update(), 
                    id=invoice_id, 
                    company=company
                )
                
                # FIX 2: Idempotency guard
                if invoice.invoice_status != 'finalized':
                    return JsonResponse(
                        {"success": False, "message": "Only finalized invoices can be voided."}, 
                        status=400
                    )

                # Reverse stock
                for line in invoice.lines.all():
                    InventoryService.reverse_sale_line(line)

                # Reverse AR balance safely
                InventoryService.reverse_invoice_on_party_balance(invoice, 'customer', sign=+1)

                # Void the invoice
                invoice.invoice_status = 'void'
                invoice.void_reason = reason
                invoice.save()
                
        except Exception as e:
            return JsonResponse({"success": False, "message": "An unexpected server error occurred."}, status=400)
        
        invoices = SaleInvoice.objects.filter(company=company).exclude(invoice_status='void').order_by('-date_dispatched')
        paginator = Paginator(invoices, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/goods_out/_table.html', {'invoices': page_obj.object_list, 'page_obj': page_obj, 'request': request, 'customers': Party.objects.filter(company=company, is_customer=True, is_deleted=False)})




class PartiesView(BaseAppView):
    template_name = "frontend/parties.html"

class SpoilageView(BaseAppView):
    template_name = "frontend/spoilage.html"

class PaymentsView(BaseAppView):
    template_name = "frontend/payments.html"

class ReportsView(BaseAppView):
    template_name = "frontend/reports.html"

class ProfileView(BaseAppView):
    template_name = "frontend/profile.html"