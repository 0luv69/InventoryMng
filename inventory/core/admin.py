from django.contrib import admin
from .models import Company, UserProfile, Unit 
from .models import (
    Company,
    UserProfile,
    Unit,
    RequestDemo,
    UserSession,
    # Supplier,
    # Customer,
    # Item,
)


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "session_key", "ip_address", "uuid", "created_at", "last_activity")
    search_fields = ("user__username", "user__email", "ip_address")
    list_filter = ("uuid", "created_at", "last_activity")
    autocomplete_fields = ("user",)
    ordering = ("-created_at",)

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "phone", "email", "currency", "created_at")
    search_fields = ("name", "slug", "phone", "email", "city", "state", "country")
    prepopulated_fields = {"slug": ("name",)}
    list_filter = ("currency", "created_at", "updated_at")
    ordering = ("name",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "company", "created_at")
    search_fields = ("user__username", "user__email", "company__name")
    list_filter = ("company", "created_at")
    autocomplete_fields = ("user", "company")
    ordering = ("company__name", "user__username")


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "company", "created_at")
    search_fields = ("name", "short_name", "company__name")
    list_filter = ("company", "created_at")
    autocomplete_fields = ("company",)
    ordering = ("company__name", "name")

@admin.register(RequestDemo)
class RequestDemoAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "created_at")
    search_fields = ("name", "email", "phone")
    list_filter = ("created_at",)
    ordering = ("-created_at",)

# @admin.register(Supplier)
# class SupplierAdmin(admin.ModelAdmin):
#     list_display = ("name", "company", "contact_person", "phone", "balance", "created_at")
#     search_fields = ("name", "contact_person", "phone", "email", "company__name")
#     list_filter = ("company", "created_at", "updated_at")
#     autocomplete_fields = ("company",)
#     ordering = ("company__name", "name")


# @admin.register(Customer)
# class CustomerAdmin(admin.ModelAdmin):
#     list_display = ("name", "company", "contact_person", "phone", "balance", "credit_limit", "created_at")
#     search_fields = ("name", "contact_person", "phone", "email", "company__name")
#     list_filter = ("company", "created_at", "updated_at")
#     autocomplete_fields = ("company",)
#     ordering = ("company__name", "name")


# @admin.register(Item)
# class ItemAdmin(admin.ModelAdmin):
#     list_display = (
#         "name",
#         "company",
#         "sku",
#         "unit",
#         "cost_price",
#         "selling_price",
#         "quantity_in_stock",
#         "low_stock_threshold",
#         "is_active",
#         "created_at",
#     )
#     search_fields = ("name", "sku", "description", "company__name", "unit__name", "unit__short_name")
#     list_filter = ("company", "unit", "is_active", "created_at", "updated_at")
#     autocomplete_fields = ("company", "unit")
#     ordering = ("company__name", "name")