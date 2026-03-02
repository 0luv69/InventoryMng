from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models import Sum, F, Q
from datetime import timedelta
from .models import Product, Customer, GoodsIn, Sale, Payment
from .forms import ProductForm, CustomerForm, GoodsInForm, SaleForm, PaymentForm


# ──────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────

def dashboard(request):
    today = timezone.now().date()
    month_start = today.replace(day=1)

    total_products = Product.objects.count()

    stock_value = Product.objects.aggregate(
        total=Sum(F('quantity_in_stock') * F('cost_price'))
    )['total'] or 0

    today_sales_qs = Sale.objects.filter(date=today)
    today_sales = today_sales_qs.aggregate(
        total=Sum(F('quantity') * F('selling_price'))
    )['total'] or 0
    today_sales_count = today_sales_qs.count()

    total_credit = Customer.objects.aggregate(
        total=Sum('balance')
    )['total'] or 0

    month_sales = Sale.objects.filter(date__gte=month_start)
    month_revenue = month_sales.aggregate(
        total=Sum(F('quantity') * F('selling_price'))
    )['total'] or 0
    month_cost = 0
    for sale in month_sales.select_related('product'):
        month_cost += sale.quantity * sale.product.cost_price
    month_profit = month_revenue - month_cost

    all_sales = Sale.objects.all().select_related('product')
    total_revenue = sum(s.quantity * s.selling_price for s in all_sales)
    total_cost = sum(s.quantity * s.product.cost_price for s in all_sales)
    total_profit = total_revenue - total_cost

    low_stock_products = Product.objects.filter(quantity_in_stock__lt=10).order_by('quantity_in_stock')[:5]
    top_credit_customers = Customer.objects.filter(balance__gt=0).order_by('-balance')[:5]

    recent_sales = Sale.objects.select_related('customer', 'product').order_by('-created_at')[:5]
    recent_payments = Payment.objects.select_related('customer').order_by('-created_at')[:5]
    recent_goods_in = GoodsIn.objects.select_related('product').order_by('-created_at')[:5]

    activity = []
    for sale in recent_sales:
        activity.append({
            'date': sale.date,
            'created_at': sale.created_at,
            'icon': '📤',
            'text': f"Sold {sale.quantity} {sale.product.name} to {sale.customer.name}",
            'amount': f"₹{sale.total_amount}",
            'type': 'sale',
            'badge': sale.payment_type,
        })
    for payment in recent_payments:
        activity.append({
            'date': payment.date,
            'created_at': payment.created_at,
            'icon': '💰',
            'text': f"{payment.customer.name} paid",
            'amount': f"₹{payment.amount}",
            'type': 'payment',
            'badge': 'payment',
        })
    for entry in recent_goods_in:
        activity.append({
            'date': entry.date,
            'created_at': entry.created_at,
            'icon': '📦',
            'text': f"Received {entry.quantity} {entry.product.name}",
            'amount': f"₹{entry.total_value}",
            'type': 'goods_in',
            'badge': 'stock',
        })
    activity.sort(key=lambda x: x['created_at'], reverse=True)
    activity = activity[:10]

    context = {
        'today': today,
        'total_products': total_products,
        'stock_value': round(stock_value, 2),
        'today_sales': round(today_sales, 2),
        'today_sales_count': today_sales_count,
        'total_credit': round(total_credit, 2),
        'month_revenue': round(month_revenue, 2),
        'month_profit': round(month_profit, 2),
        'total_revenue': round(total_revenue, 2),
        'total_profit': round(total_profit, 2),
        'low_stock_products': low_stock_products,
        'top_credit_customers': top_credit_customers,
        'activity': activity,
    }
    return render(request, 'core/dashboard.html', context)


# ──────────────────────────────────────
# PRODUCT VIEWS
# ──────────────────────────────────────

def product_list(request):
    products = Product.objects.all().order_by('-created_at')

    search = request.GET.get('search', '')
    if search:
        products = products.filter(name__icontains=search)

    stock_filter = request.GET.get('stock', '')
    if stock_filter == 'low':
        products = products.filter(quantity_in_stock__lt=10)
    elif stock_filter == 'out':
        products = products.filter(quantity_in_stock=0)

    context = {
        'today': timezone.now().date(),
        'products': products,
        'search': search,
        'stock_filter': stock_filter,
    }
    return render(request, 'core/product_list.html', context)


def product_add(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('product_list')
    else:
        form = ProductForm()

    context = {
        'today': timezone.now().date(),
        'form': form,
        'edit_mode': False,
    }
    return render(request, 'core/product_form.html', context)


def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)

    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)

    context = {
        'today': timezone.now().date(),
        'form': form,
        'product': product,
        'edit_mode': True,
    }
    return render(request, 'core/product_form.html', context)


def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)

    if request.method == 'POST':
        product.delete()
        return redirect('product_list')

    context = {
        'today': timezone.now().date(),
        'product': product,
    }
    return render(request, 'core/product_delete.html', context)


# ──────────────────────────────────────
# CUSTOMER VIEWS
# ──────────────────────────────────────

def customer_list(request):
    customers = Customer.objects.all().order_by('-created_at')

    search = request.GET.get('search', '')
    if search:
        customers = customers.filter(
            Q(name__icontains=search) | Q(phone__icontains=search)
        )

    credit_filter = request.GET.get('credit', '')
    if credit_filter == 'owing':
        customers = customers.filter(balance__gt=0)
    elif credit_filter == 'clear':
        customers = customers.filter(balance__lte=0)

    total_credit = Customer.objects.filter(balance__gt=0).aggregate(
        total=Sum('balance')
    )['total'] or 0

    context = {
        'today': timezone.now().date(),
        'customers': customers,
        'total_credit': round(total_credit, 2),
        'search': search,
        'credit_filter': credit_filter,
    }
    return render(request, 'core/customer_list.html', context)


def customer_add(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('customer_list')
    else:
        form = CustomerForm()

    context = {
        'today': timezone.now().date(),
        'form': form,
        'edit_mode': False,
    }
    return render(request, 'core/customer_form.html', context)


def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            return redirect('customer_list')
    else:
        form = CustomerForm(instance=customer)

    context = {
        'today': timezone.now().date(),
        'form': form,
        'customer': customer,
        'edit_mode': True,
    }
    return render(request, 'core/customer_form.html', context)


def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    if request.method == 'POST':
        customer.delete()
        return redirect('customer_list')

    context = {
        'today': timezone.now().date(),
        'customer': customer,
    }
    return render(request, 'core/customer_delete.html', context)


def customer_ledger(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    sales = Sale.objects.filter(customer=customer).select_related('product')
    payments = Payment.objects.filter(customer=customer)

    ledger = []
    for sale in sales:
        ledger.append({
            'date': sale.date,
            'type': 'sale',
            'description': f"{sale.quantity} {sale.product.get_unit_display()} of {sale.product.name}",
            'debit': sale.quantity * sale.selling_price if sale.payment_type == 'credit' else 0,
            'credit': 0,
            'payment_type': sale.payment_type,
        })
    for payment in payments:
        ledger.append({
            'date': payment.date,
            'type': 'payment',
            'description': payment.notes or 'Payment received',
            'debit': 0,
            'credit': payment.amount,
        })

    ledger.sort(key=lambda x: x['date'], reverse=True)

    total_purchased = sum(s.quantity * s.selling_price for s in sales)
    total_paid = sum(p.amount for p in payments)

    context = {
        'today': timezone.now().date(),
        'customer': customer,
        'ledger': ledger,
        'total_purchased': round(total_purchased, 2),
        'total_paid': round(total_paid, 2),
        'sales_count': sales.count(),
    }
    return render(request, 'core/customer_ledger.html', context)


# ──────────────────────────────────────
# GOODS IN VIEWS
# ──────────────────────────────────────

def goods_in_list(request):
    entries = GoodsIn.objects.all().select_related('product')

    search = request.GET.get('search', '')
    if search:
        entries = entries.filter(
            Q(product__name__icontains=search) | Q(supplier_name__icontains=search)
        )

    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if date_from:
        entries = entries.filter(date__gte=date_from)
    if date_to:
        entries = entries.filter(date__lte=date_to)

    total_entries = entries.count()
    total_value = sum(e.quantity * e.cost_price_at_entry for e in entries)

    context = {
        'today': timezone.now().date(),
        'entries': entries,
        'total_entries': total_entries,
        'total_value': round(total_value, 2),
        'search': search,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'core/goods_in_list.html', context)


def goods_in_add(request):
    if request.method == 'POST':
        form = GoodsInForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('goods_in_list')
    else:
        form = GoodsInForm()
        form.fields['date'].initial = timezone.now().date()

    context = {
        'today': timezone.now().date(),
        'form': form,
    }
    return render(request, 'core/goods_in_form.html', context)


# ──────────────────────────────────────
# SALE VIEWS
# ──────────────────────────────────────

def sale_list(request):
    sales = Sale.objects.all().select_related('customer', 'product')

    search = request.GET.get('search', '')
    if search:
        sales = sales.filter(
            Q(customer__name__icontains=search) | Q(product__name__icontains=search)
        )

    payment_filter = request.GET.get('payment', '')
    if payment_filter in ['cash', 'credit']:
        sales = sales.filter(payment_type=payment_filter)

    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)

    total_sales = sales.count()
    total_revenue = sum(s.quantity * s.selling_price for s in sales)
    total_credit_sales = sum(
        s.quantity * s.selling_price for s in sales if s.payment_type == 'credit'
    )
    total_cash_sales = total_revenue - total_credit_sales

    context = {
        'today': timezone.now().date(),
        'sales': sales,
        'total_sales': total_sales,
        'total_revenue': round(total_revenue, 2),
        'total_credit_sales': round(total_credit_sales, 2),
        'total_cash_sales': round(total_cash_sales, 2),
        'search': search,
        'payment_filter': payment_filter,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'core/sale_list.html', context)


def sale_add(request):
    if request.method == 'POST':
        form = SaleForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('sale_list')
    else:
        form = SaleForm()
        form.fields['date'].initial = timezone.now().date()

    products_data = {
        p.id: {
            'selling_price': str(p.selling_price),
            'stock': str(p.quantity_in_stock),
            'unit': p.get_unit_display(),
        }
        for p in Product.objects.all()
    }

    context = {
        'today': timezone.now().date(),
        'form': form,
        'products_data': products_data,
    }
    return render(request, 'core/sale_form.html', context)


# ──────────────────────────────────────
# PAYMENT VIEWS
# ──────────────────────────────────────

def payment_list(request):
    payments = Payment.objects.all().select_related('customer')

    search = request.GET.get('search', '')
    if search:
        payments = payments.filter(customer__name__icontains=search)

    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if date_from:
        payments = payments.filter(date__gte=date_from)
    if date_to:
        payments = payments.filter(date__lte=date_to)

    total_collected = payments.aggregate(
        total=Sum('amount')
    )['total'] or 0

    context = {
        'today': timezone.now().date(),
        'payments': payments,
        'total_payments': payments.count(),
        'total_collected': round(total_collected, 2),
        'search': search,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'core/payment_list.html', context)


def payment_add(request):
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('payment_list')
    else:
        form = PaymentForm()
        form.fields['date'].initial = timezone.now().date()

    customers_data = {
        c.id: {
            'balance': str(c.balance),
            'name': c.name,
        }
        for c in Customer.objects.filter(balance__gt=0)
    }

    context = {
        'today': timezone.now().date(),
        'form': form,
        'customers_data': customers_data,
    }
    return render(request, 'core/payment_form.html', context)