from django.contrib import admin
from .models import Party

@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_customer', 'is_supplier', 'phone', 'balance', 'credit_limit', 'status')
    list_filter = ('is_customer', 'is_supplier', 'status')
    search_fields = ('name', 'phone', 'contact_person')