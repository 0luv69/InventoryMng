from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.conf import settings
import uuid

# ==========================================
# 1. CUSTOM USER MANAGER & USER
# ==========================================
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, blank=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    objects = UserManager()

    def __str__(self):
        return self.email


# ==========================================
# 2. SaaS SUBSCRIPTION PLANS
# ==========================================
class Plan(models.Model):
    name = models.CharField(max_length=50, unique=True) # e.g., Trial, Pro, Lifetime
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    duration_days = models.PositiveIntegerField(default=0, help_text="0 for Lifetime")
    max_items = models.PositiveIntegerField(default=50, help_text="0 for unlimited")
    max_invoices_per_month = models.PositiveIntegerField(default=50, help_text="0 for unlimited")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


# ==========================================
# 3. COMPANY (MULTI-TENANT ROOT)
# ==========================================
class Company(models.Model):
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    logo = models.ImageField(upload_to="company_logos/", null=True, blank=True)
    is_active = models.BooleanField(default=True) # SuperAdmin can suspend
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


# ==========================================
# 4. SUBSCRIPTION (LINKS COMPANY TO PLAN)
# ==========================================
class Subscription(models.Model):
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    start_date = models.DateField(auto_now_add=True)
    end_date = models.DateField(null=True, blank=True, help_text="Null for Lifetime plans")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.company.name} - {self.plan.name}"


# ==========================================
# 5. USER PROFILE (LINKS USER TO COMPANY)
# ==========================================
class UserProfile(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        ADMIN = 'admin', 'Admin'
        STAFF = 'staff', 'Staff'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='members', null=True, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STAFF)
    is_owner = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} ({self.company.name if self.company else 'No Company'})"


# ==========================================
# 6. AUDIT LOG (ACTIVITY TRACKING)
# ==========================================
class AuditLog(models.Model):
    class ActionType(models.TextChoices):
        CREATE = 'create', 'Create'
        UPDATE = 'update', 'Update'
        DELETE = 'delete', 'Delete'
        LOGIN = 'login', 'Login'
        LOGOUT = 'logout', 'Logout'

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='audit_logs', null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action_type = models.CharField(max_length=10, choices=ActionType.choices)
    entity_name = models.CharField(max_length=100) # e.g., 'SaleInvoice', 'Item'
    entity_id = models.CharField(max_length=50, blank=True) # ID of the affected record
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.action_type} - {self.entity_name}"
    

# ==========================================
# 7. COMPANY SETTINGS (PER-TENANT CONFIG)
# ==========================================
class CompanySetting(models.Model):
    """ Stores configuration specific to a company's SaaS instance """
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='settings')
    
    # Financials
    currency = models.CharField(max_length=3, default='NPR')
    enable_vat = models.BooleanField(default=True, help_text="Toggle 13% VAT calculations globally")
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=13.00)
    
    # Defaults for fast data entry
    default_warehouse = models.ForeignKey(
        'inventory.Warehouse', on_delete=models.SET_NULL, null=True, blank=True
    )
    default_price_tier = models.ForeignKey(
        'catalog.PriceTier', on_delete=models.SET_NULL, null=True, blank=True
    )
    
    # Invoice Formatting
    sale_invoice_prefix = models.CharField(max_length=20, default='INV-')
    purchase_invoice_prefix = models.CharField(max_length=20, default='PUR-')
    
    # Low Stock Alerts
    enable_low_stock_alerts = models.BooleanField(default=True)

    def __str__(self):
        return f"Settings for {self.company.name}"


# ==========================================
# 8. NOTIFICATIONS (IN-APP ALERTS)
# ==========================================
class Notification(models.Model):
    """ In-app notifications for users (e.g., Low Stock, Expiring Batches) """
    class NotificationType(models.TextChoices):
        LOW_STOCK = 'low_stock', 'Low Stock'
        EXPIRY_ALERT = 'expiry_alert', 'Expiry Alert'
        SUBSCRIPTION = 'subscription', 'Subscription Alert'
        SYSTEM = 'system', 'System Notification'

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='notifications')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', null=True, blank=True, help_text="Leave blank for all company users")
    
    notification_type = models.CharField(max_length=20, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    
    # Optional links to take the user directly to the issue
    redirect_url = models.CharField(max_length=255, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.notification_type} - {self.title}"











