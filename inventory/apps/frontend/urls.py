from django.urls import path
from . import views

app_name = 'frontend' # This allows us to use frontend:dashboard

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('items/', views.ItemsView.as_view(), name='items'),
    path('parties/', views.PartiesView.as_view(), name='parties'),
    path('goods-in/', views.GoodsInView.as_view(), name='goods_in'),
    path('goods-out/', views.GoodsOutView.as_view(), name='goods_out'),
    path('spoilage/', views.SpoilageView.as_view(), name='spoilage'),
    path('payments/', views.PaymentsView.as_view(), name='payments'),
    path('reports/', views.ReportsView.as_view(), name='reports'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
]