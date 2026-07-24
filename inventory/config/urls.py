from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.catalog.api_views import CategoryViewSet, UnitViewSet, ItemViewSet
from apps.parties.api_views import PartyViewSet

from apps.transactions.api_views import (
    PurchaseInvoiceViewSet,
    SaleInvoiceViewSet,
    PaymentViewSet,
)


from django.conf import settings
from django.conf.urls.static import static


from apps.reports.views import dashboard_data_api



router = DefaultRouter()
router.register(r'categories', CategoryViewSet)
router.register(r'units', UnitViewSet)
router.register(r'items', ItemViewSet)
router.register(r'parties', PartyViewSet)

router.register(r'purchase-invoices', PurchaseInvoiceViewSet)
router.register(r'sale-invoices', SaleInvoiceViewSet)
router.register(r'payments', PaymentViewSet)


urlpatterns = [
    path('admin/', admin.site.urls),
    
    # JWT Auth Endpoints
    path('api/auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # API Routes
    path('api/', include(router.urls)),


    path('api/dashboard/data/', dashboard_data_api, name='dashboard_data_api'),

    path('', include('apps.frontend.urls'))
]


# Serve media and static files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)