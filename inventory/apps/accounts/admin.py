from django.contrib import admin
from .models import Notification, User, Plan, Company, Subscription, UserProfile, AuditLog, CompanySetting

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'phone_number', 'is_staff', 'is_active')
    search_fields = ('email', 'phone_number')

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'duration_days', 'max_items', 'is_active')

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    search_fields = ('name',)

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('company', 'plan', 'start_date', 'end_date', 'is_active')

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'role', 'is_owner')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'action_type', 'entity_name', 'created_at')
    readonly_fields = [field.name for field in AuditLog._meta.fields]





@admin.register(CompanySetting)
class CompanySettingAdmin(admin.ModelAdmin):
    list_display = ('company', 'currency', 'enable_vat', 'vat_percentage', 'sale_invoice_prefix')

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('company', 'notification_type', 'title', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')