from rest_framework import viewsets
from rest_framework.filters import SearchFilter
from .models import Party
from .serializers import PartySerializer
from apps.core.api import CompanyScopedViewSet

class PartyViewSet(CompanyScopedViewSet):
    queryset = Party.objects.all()
    serializer_class = PartySerializer
    filter_backends = [SearchFilter]
    search_fields = ['name', 'phone', 'contact_person']