from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Products
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.product_add, name='product_add'),
    path('products/<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),


        # Customers
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/add/', views.customer_add, name='customer_add'),
    path('customers/<int:pk>/edit/', views.customer_edit, name='customer_edit'),
    path('customers/<int:pk>/delete/', views.customer_delete, name='customer_delete'),
    path('customers/<int:pk>/ledger/', views.customer_ledger, name='customer_ledger'),


    # Goods In
    path('goods-in/', views.goods_in_list, name='goods_in_list'),
    path('goods-in/add/', views.goods_in_add, name='goods_in_add'),


    # Sales
    path('sales/', views.sale_list, name='sale_list'),
    path('sales/add/', views.sale_add, name='sale_add'),


    # Payments
    path('payments/', views.payment_list, name='payment_list'),
    path('payments/add/', views.payment_add, name='payment_add'),
]