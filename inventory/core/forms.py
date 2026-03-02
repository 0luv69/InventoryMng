from django import forms
from .models import Product, Customer, GoodsIn, Sale, Payment


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'unit', 'cost_price', 'selling_price']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'w-full px-4 py-2.5 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent text-sm',
            })
        self.fields['name'].widget.attrs['placeholder'] = 'e.g. Cement Bag'
        self.fields['cost_price'].widget.attrs['placeholder'] = '0.00'
        self.fields['selling_price'].widget.attrs['placeholder'] = '0.00'


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'products']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        base_classes = 'w-full px-4 py-2.5 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent text-sm'

        self.fields['name'].widget.attrs.update({
            'class': base_classes,
            'placeholder': 'e.g. Ramesh Kumar',
        })
        self.fields['phone'].widget.attrs.update({
            'class': base_classes,
            'placeholder': 'e.g. 9876543210',
        })
        # Checkbox style for products (multi-select)
        self.fields['products'].widget = forms.CheckboxSelectMultiple()
        self.fields['products'].queryset = Product.objects.all().order_by('name')
        self.fields['products'].required = False



class GoodsInForm(forms.ModelForm):
    class Meta:
        model = GoodsIn
        fields = ['product', 'quantity', 'cost_price_at_entry', 'supplier_name', 'date', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        base_classes = 'w-full px-4 py-2.5 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent text-sm'

        self.fields['product'].widget.attrs.update({'class': base_classes})
        self.fields['quantity'].widget.attrs.update({
            'class': base_classes,
            'placeholder': 'e.g. 100',
        })
        self.fields['cost_price_at_entry'].widget.attrs.update({
            'class': base_classes,
            'placeholder': '0.00',
        })
        self.fields['supplier_name'].widget.attrs.update({
            'class': base_classes,
            'placeholder': 'e.g. ABC Suppliers',
        })
        self.fields['date'].widget = forms.DateInput(attrs={
            'class': base_classes,
            'type': 'date',
        })
        self.fields['notes'].widget.attrs.update({
            'class': base_classes + ' h-20',
            'placeholder': 'Any remarks about this batch...',
        })

        self.fields['supplier_name'].required = False
        self.fields['notes'].required = False



class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ['customer', 'product', 'quantity', 'selling_price', 'payment_type', 'date']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        base_classes = 'w-full px-4 py-2.5 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent text-sm'

        self.fields['customer'].widget.attrs.update({'class': base_classes})
        self.fields['product'].widget.attrs.update({'class': base_classes})
        self.fields['quantity'].widget.attrs.update({
            'class': base_classes,
            'placeholder': 'e.g. 10',
        })
        self.fields['selling_price'].widget.attrs.update({
            'class': base_classes,
            'placeholder': '0.00',
        })
        self.fields['payment_type'].widget.attrs.update({'class': base_classes})
        self.fields['date'].widget = forms.DateInput(attrs={
            'class': base_classes,
            'type': 'date',
        })

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        quantity = cleaned_data.get('quantity')

        if product and quantity:
            if quantity > product.quantity_in_stock:
                raise forms.ValidationError(
                    f"Not enough stock! Only {product.quantity_in_stock} {product.get_unit_display()} of {product.name} available."
                )
            if quantity <= 0:
                raise forms.ValidationError("Quantity must be greater than zero.")

        return cleaned_data



class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['customer', 'amount', 'date', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        base_classes = 'w-full px-4 py-2.5 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent text-sm'

        self.fields['customer'].widget.attrs.update({'class': base_classes})
        # Only show customers who owe money
        self.fields['customer'].queryset = Customer.objects.filter(balance__gt=0).order_by('name')
        self.fields['amount'].widget.attrs.update({
            'class': base_classes,
            'placeholder': '0.00',
        })
        self.fields['date'].widget = forms.DateInput(attrs={
            'class': base_classes,
            'type': 'date',
        })
        self.fields['notes'].widget.attrs.update({
            'class': base_classes + ' h-20',
            'placeholder': 'e.g. Paid via UPI, Partial payment...',
        })
        self.fields['notes'].required = False

    def clean(self):
        cleaned_data = super().clean()
        customer = cleaned_data.get('customer')
        amount = cleaned_data.get('amount')

        if customer and amount:
            if amount <= 0:
                raise forms.ValidationError("Payment amount must be greater than zero.")
            if amount > customer.balance:
                raise forms.ValidationError(
                    f"{customer.name} only owes ₹{customer.balance}. Cannot accept more than that."
                )

        return cleaned_data