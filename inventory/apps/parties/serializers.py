from rest_framework import serializers
from .models import Party

class PartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ['id', 'name', 'is_supplier', 'is_customer', 'phone', 'email', 'address', 
                  'pan_vat', 'balance', 'credit_limit', 'status']