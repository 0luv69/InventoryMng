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
        name = request.POST.get('name', '').strip() # Safely get name
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
        # Set all company tiers to False, then set the selected one to True
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
        context = {
            'units': Unit.objects.filter(company=company),
            'categories': Category.objects.filter(company=company),
            'price_tiers': PriceTier.objects.filter(company=company), 
            'default_tier_id': PriceTier.objects.filter(company=company, is_default=True).first().id if PriceTier.objects.filter(company=company, is_default=True).exists() else None,
        }
        return render(request, 'frontend/items/items.html', context)

class ItemFormView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        item_id = request.GET.get('id')
        is_editable = request.GET.get('editable', '0') == '1'
        item = None
        uom_json = '[]'
        prices_json = '[]'

        if item_id:
            item = get_object_or_404(Item, id=item_id, company=company)
            uoms = ItemUOM.objects.filter(item=item).select_related('unit')
            uom_list = [{'unit_id': u.unit_id, 'factor': str(u.conversion_factor)} for u in uoms]
            uom_json = json.dumps(uom_list)
            
            prices = ItemPrice.objects.filter(item=item).select_related('price_tier')
            prices_list = [{'tier_id': p.price_tier_id, 'price': str(p.price), 
                            'is_default': p.is_default,
                            'entry_unit_id': p.entry_unit_id

                            } for p in prices]
            prices_json = json.dumps(prices_list)

        # EFFICIENCY FIX: Query once, let DB sort and slice
        units_qs = Unit.objects.filter(company=company).order_by('name')
        cats_qs = Category.objects.filter(company=company).order_by('name')
        sups_qs = Party.objects.filter(company=company, is_supplier=True, is_removed=False).order_by('name')
        tiers_qs = PriceTier.objects.filter(company=company)

        recent_cats = cats_qs.order_by('-created_at')[:4]
        recent_units = units_qs.order_by('-created_at')[:4]
        recent_sups = sups_qs.order_by('-created_at')[:4]
        
        default_tier = tiers_qs.filter(is_default=True).first()

        context = {
            'item': item,
            'is_editable': is_editable,
            'units': units_qs,
            'categories': cats_qs,
            'suppliers': sups_qs,
            'price_tiers': tiers_qs,
            'uom_json': uom_json,
            'prices_json': prices_json,
            'recent_categories': json.dumps([{'id': c.id, 'name': c.name} for c in recent_cats]),
            'recent_units': json.dumps([{'id': u.id, 'name': u.name} for u in recent_units]),
            'recent_suppliers': json.dumps([{'id': s.id, 'name': s.name} for s in recent_sups]),
            'unit_map_json': json.dumps({str(u.id): u.name for u in units_qs}),
            'default_tier_id': default_tier.id if default_tier else None,
            'cost_entry_unit_id': item.cost_entry_unit_id if item else None,
        }
        return render(request, 'frontend/items/_form.html', context)

class ItemsTableView(BaseAppView):
    def get(self, request):
        company = self.get_company()
        
        # EFFICIENCY FIX: select_related stops N+1 queries for category/base_unit
        items = Item.objects.filter(company=company).exclude(status='deleted').select_related(
            'category', 'base_unit'
        ).annotate(
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

        paginator = Paginator(items, self.pagination_size)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {
            'items': page_obj.object_list,
            'page_obj': page_obj,
            'request': request,
        }
        return render(request, 'frontend/items/_table.html', context)


# 2. ItemSaveView
class ItemSaveView(BaseAppView):
    @transaction.atomic
    def post(self, request):
        company = self.get_company()
        item_id = request.POST.get('id')


        base_unit_id = request.POST.get('base_unit')
        if not base_unit_id:
            return JsonResponse({"success": False, "message": "Base Unit is required."}, status=400)


        # Parse and Validate UOMs
        uom_unit_ids = request.POST.getlist('uom_unit_id[]')
        uom_factors = request.POST.getlist('uom_factor[]')

        parsed_uoms = []
        seen_uoms = set()

        for i in range(len(uom_unit_ids)):
            if uom_unit_ids[i] and uom_factors[i]:
                if uom_unit_ids[i] == base_unit_id:
                    return JsonResponse({"success": False, "message": "Base unit can't be added as its own UOM conversion."}, status=400)
                if uom_unit_ids[i] in seen_uoms:
                    return JsonResponse({"success": False, "message": "Duplicate Unit found in UOM Conversions. Please select each unit only once."}, status=400)

                # Bug D Fix: Explicitly validate conversion factor
                try:
                    factor = Decimal(uom_factors[i])
                    if factor <= 0:
                        raise ValueError
                except (InvalidOperation, ValueError):
                    return JsonResponse({"success": False, "message": f"Invalid conversion factor: {uom_factors[i]}. Must be > 0."}, status=400)

                seen_uoms.add(uom_unit_ids[i])
                parsed_uoms.append({'unit_id': uom_unit_ids[i], 'factor': factor})


        # Parse and Validate Prices
        tier_ids = request.POST.getlist('price_tier_id[]')
        tier_prices = request.POST.getlist('price_amount[]')
        default_flags = request.POST.getlist('price_is_default[]')
        entry_units = request.POST.getlist('price_entry_unit[]')

        parsed_prices = []
        seen_tiers = set()
        default_count = 0

        for i in range(len(tier_ids)):
            if tier_ids[i] and tier_prices[i]:
                if tier_ids[i] in seen_tiers:
                    return JsonResponse({"success": False, "message": "Duplicate Price Tier found. Please select each tier only once."}, status=400)

                # Fix: Explicitly validate price amount to ensure it's a valid decimal and non-negative
                try:
                    price = Decimal(tier_prices[i])
                    if price < 0:
                        raise ValueError
                except (InvalidOperation, ValueError):
                    return JsonResponse({"success": False, "message": f"Invalid price amount: {tier_prices[i]}."}, status=400)

                is_default = (default_flags[i] == '1') if i < len(default_flags) else False
                if is_default:
                    default_count += 1

                seen_tiers.add(tier_ids[i])
                parsed_prices.append({
                    'tier_id': tier_ids[i],
                    'price': price,
                    'is_default': is_default,
                    'entry_unit_id': entry_units[i] if i < len(entry_units) else None
                })


        if default_count > 1:
            return JsonResponse({"success": False, "message": "Multiple default prices found. Please select only one default price."}, status=400)


        
        if item_id:
            item = get_object_or_404(Item, id=item_id, company=company)
        else:
            item = Item(company=company)
            item.created_by = request.user


        item.name = request.POST.get('name')
        item.category_id = request.POST.get('category') or None
        item.base_unit_id = base_unit_id
        item.barcode = request.POST.get('barcode')
        item.default_supplier_id = request.POST.get('default_supplier') or None
        item.status = 'active' if request.POST.get('is_active') == 'on' else 'inactive'
        item.cost_entry_unit_id = request.POST.get('cost_entry_unit') or None
        
        try:
            cost_price = Decimal(request.POST.get('cost_price'))
            if cost_price < 0:
                raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            return JsonResponse({"success": False, "message": "Invalid Cost Price. Must be a positive number."}, status=400)

        # Fix: Filesystem operations deferred to on_commit

        old_image_path = item.image.path if item.image else None
        clear_image_flag = request.POST.get('clear_image') == '1'
        new_image_uploaded = 'image' in request.FILES
        
        if new_image_uploaded:
            item.image = request.FILES['image']
        elif clear_image_flag and item.image:
            item.image = None  # Nullify DB field

        try:
            item.save()
        except IntegrityError:
            return JsonResponse({"success": False, "message": "An item with this name already exists."}, status=400)
        
        # Synchronize UOMs
        item.uom_conversions.all().delete()
        for uom in parsed_uoms:
            ItemUOM.objects.create(
                company=company, item=item, unit_id=uom['unit_id'], 
                conversion_factor=uom['factor'], created_by=request.user
            )

        # Synchronize Prices
        item.prices.all().delete()
        for price in parsed_prices:
            ItemPrice.objects.create(
                company=company, item=item, price_tier_id=price['tier_id'], 
                price=price['price'], created_by=request.user,
                entry_unit_id=price['entry_unit_id'],
                is_default=price['is_default']
            )


        # Fix for safe file deletion
        new_image_path = item.image.path if item.image else None
        if old_image_path and old_image_path != new_image_path:
            def delete_old_file():
                if default_storage.exists(old_image_path):
                    default_storage.delete(old_image_path)
            transaction.on_commit(delete_old_file)
        
        # Fetch updated list for table render
        items = Item.objects.filter(company=company).exclude(status='deleted').select_related(
            'category', 'base_unit'
        ).annotate(
            total_stock_calc=Sum('stock_batches__quantity')
        ).order_by('-created_at')
        paginator = Paginator(items, self.pagination_size)
        page_obj = paginator.get_page(1)
        
        return render(request, 'frontend/items/_table.html', {'items': page_obj.object_list, 'page_obj': page_obj, 'request': request})
        











# 3. Update ItemDeleteView
class ItemDeleteView(BaseAppView):
    def post(self, request, item_id):
        company = self.get_company()
        item = get_object_or_404(Item, id=item_id, company=company)
        
        reason = request.POST.get('delete_reason', 'No reason provided')
        
        item.status = 'deleted'
        item.delete_reason = reason
        item.save()
        
        # EFFICIENCY FIX: select_related here too
        items = Item.objects.filter(company=company).exclude(status='deleted').select_related(
            'category', 'base_unit'
        ).annotate(
            total_stock_calc=Sum('stock_batches__quantity')
        ).order_by('-created_at')
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

        paginator = Paginator(invoices, self.pagination_size)
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

        # EFFICIENCY FIX: Fetch all items in one query
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
        paginator = Paginator(invoices, self.pagination_size)
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

        paginator = Paginator(invoices, self.pagination_size)
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

        customers = Party.objects.filter(company=company, is_customer=True, is_removed=False)
        warehouses = Warehouse.objects.filter(company=company, is_active=True)
        
        default_tier = PriceTier.objects.filter(company=company, is_default=True).first()
        
        # EFFICIENCY FIX: Use Prefetch to get default prices in 2 queries instead of N+1
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

                # EFFICIENCY FIX: Fetch all items in one query
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
        paginator = Paginator(invoices, self.pagination_size)
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