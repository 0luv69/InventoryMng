from rest_framework import viewsets
from rest_framework.filters import SearchFilter
from .models import PurchaseInvoice, SaleInvoice, Payment
from .serializers import PurchaseInvoiceSerializer, SaleInvoiceSerializer, PaymentSerializer
from apps.core.api import CompanyScopedViewSet

class PurchaseInvoiceViewSet(CompanyScopedViewSet):
    queryset = PurchaseInvoice.objects.prefetch_related('lines').all()
    serializer_class = PurchaseInvoiceSerializer
    filter_backends = [SearchFilter]
    search_fields = ['reference_no', 'supplier__name']

class SaleInvoiceViewSet(CompanyScopedViewSet):
    queryset = SaleInvoice.objects.prefetch_related('lines').all()
    serializer_class = SaleInvoiceSerializer
    filter_backends = [SearchFilter]
    search_fields = ['reference_no', 'customer__name']

class PaymentViewSet(CompanyScopedViewSet):
    queryset = Payment.objects.prefetch_related('allocations').all()
    serializer_class = PaymentSerializer
    filter_backends = [SearchFilter]
    search_fields = ['reference_no', 'party__name']