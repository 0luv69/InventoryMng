# parties.models
from django.db import models
from apps.core.models import BaseModel
import uuid

class Party(BaseModel):
    """ Represents a business entity, which can be a supplier, customer, or both.
    """
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=200)
    
    is_supplier = models.BooleanField(default=False)
    is_customer = models.BooleanField(default=False)
    
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    pan_vat = models.CharField("PAN/VAT Number", max_length=50, blank=True)
    
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="0 means no limit")
    
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta(BaseModel.Meta):
        ordering = ['name']
        constraints = [
            # FIX: Added ~Q(is_deleted=True) so deleted parties can be recreated
            models.UniqueConstraint(fields=['company', 'name'], condition=~models.Q(is_deleted=True), name='uniq_party_name_per_company')
        ]

    def __str__(self):
        return self.name