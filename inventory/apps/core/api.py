from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

class CompanyScopedViewSet(viewsets.ModelViewSet):
    """
    Custom ViewSet that automatically filters querysets by the user's company
    and forces the company field on create.
    """
    permission_classes = [IsAuthenticated]

    def get_company(self):
        # Assumes UserProfile is linked 1-to-1 with User
        return self.request.user.profile.company

    def get_queryset(self):
        company = self.get_company()
        return super().get_queryset().filter(company=company)

    def perform_create(self, serializer):
        # Automatically inject the company when creating
        company = self.get_company()
        serializer.save(company=company, created_by=self.request.user)