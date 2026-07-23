from rest_framework import serializers
from .models import Category, Unit, Item, ItemUOM, PriceTier, ItemPrice

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'description']

class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ['id', 'name', 'short_name']

class ItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    base_unit_name = serializers.CharField(source='base_unit.short_name', read_only=True)
    total_stock = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    
    class Meta:
        model = Item
        fields = ['id', 'name', 'category', 'category_name', 'base_unit', 'base_unit_name', 
                  'barcode', 'cost_price', 'total_stock', 'status', 'low_stock_threshold']