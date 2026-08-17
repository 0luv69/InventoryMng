#core.models

from django.db import models
from django.conf import settings

class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

class BaseModel(models.Model):
    """
    Abstract base model for all multi-tenant models.
    Enforces company isolation and standard timestamps.
    """
    company = models.ForeignKey(
        'accounts.Company', 
        on_delete=models.CASCADE, 
        related_name="%(class)ss", # e.g., items, parties
        null=True, blank=True # Null for SuperAdmin level data
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_%(class)ss")
    
    # Universal Soft Delete
    is_deleted = models.BooleanField(default=False)
    
    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True