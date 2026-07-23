from rest_framework import viewsets
from rest_framework.filters import SearchFilter
from .models import Category, Unit, Item
from .serializers import CategorySerializer, UnitSerializer, ItemSerializer
from apps.core.api import CompanyScopedViewSet

class CategoryViewSet(CompanyScopedViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

class UnitViewSet(CompanyScopedViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer

class ItemViewSet(CompanyScopedViewSet):
    queryset = Item.objects.select_related('category', 'base_unit').all()
    serializer_class = ItemSerializer
    filter_backends = [SearchFilter]
    search_fields = ['name', 'barcode']