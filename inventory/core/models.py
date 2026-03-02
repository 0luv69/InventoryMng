from django.db import models
from django.utils import timezone


class Product(models.Model):
    UNIT_CHOICES = [
        ('piece', 'Piece'),
        ('kg', 'Kilogram'),
        ('bag', 'Bag'),
        ('box', 'Box'),
        ('litre', 'Litre'),
        ('meter', 'Meter'),
        ('dozen', 'Dozen'),
    ]

    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='piece')
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price you pay to buy this")
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Default price you sell at")
    quantity_in_stock = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.get_unit_display()})"

    @property
    def stock_value(self):
        """Total value of current stock at cost price"""
        return self.quantity_in_stock * self.cost_price


class Customer(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=15, blank=True, null=True)
    products = models.ManyToManyField(Product, blank=True, help_text="Products this customer usually buys")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Amount customer owes (credit)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (Balance: ₹{self.balance})"


class GoodsIn(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='goods_in')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price_at_entry = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price paid for this batch")
    supplier_name = models.CharField(max_length=200, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Goods In"
        verbose_name_plural = "Goods In"
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.quantity} {self.product.get_unit_display()} of {self.product.name} on {self.date}"

    @property
    def total_value(self):
        """Total value of this entry"""
        return round(self.quantity * self.cost_price_at_entry, 2)

    def save(self, *args, **kwargs):
        # If this is a NEW entry (no pk yet), add to stock
        if not self.pk:
            self.product.quantity_in_stock += self.quantity
            self.product.save()
        super().save(*args, **kwargs)
    




class Sale(models.Model):
    PAYMENT_CHOICES = [
        ('cash', 'Cash'),
        ('credit', 'Credit'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='sales')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='sales')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price charged for this sale")
    payment_type = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default='cash')
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.customer.name} bought {self.quantity} {self.product.name} on {self.date}"

    @property
    def total_amount(self):
        return self.quantity * self.selling_price

    @property
    def profit(self):
        """Profit on this sale"""
        cost = self.quantity * self.product.cost_price
        revenue = self.quantity * self.selling_price
        return revenue - cost

    def save(self, *args, **kwargs):
        if not self.pk:
            # Deduct stock
            self.product.quantity_in_stock -= self.quantity
            self.product.save()

            # If credit sale, add to customer balance
            if self.payment_type == 'credit':
                self.customer.balance += self.total_amount
                self.customer.save()
        super().save(*args, **kwargs)


class Payment(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.customer.name} paid ₹{self.amount} on {self.date}"

    def save(self, *args, **kwargs):
        if not self.pk:
            # Reduce customer balance when payment is made
            self.customer.balance -= self.amount
            self.customer.save()
        super().save(*args, **kwargs)