from django.db import models
from apps.core.models import BaseModel
import uuid

class Party(BaseModel):
    """ Unified model for both Suppliers and Customers """
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=200)
    
    # Type flags (Allows a party to be both)
    is_supplier = models.BooleanField(default=False)
    is_customer = models.BooleanField(default=False)
    
    # Contact Info
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    pan_vat = models.CharField("PAN/VAT Number", max_length=50, blank=True)
    
    # Financials
    # +ve means they owe us (Customer), -ve means we owe them (Supplier)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="0 means no limit")
    
    # State
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    is_removed = models.BooleanField(default=False) # Soft delete

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='uniq_party_name_per_company')
        ]

    def __str__(self):
        return self.name