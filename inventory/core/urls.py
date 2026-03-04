from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('t', views.temp, name='temp'),


    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('signup/', views.register_view, name='register'),

    path("login/api/", views.login_api, name="login_api"),
    path("register/api/", views.register_api, name="register_api"),



    path('app/dashboard/', views.dashboard, name='dashboard'),
    path('app/', views.app_home, name='app_home'),

    path('app/items/', views.items_view, name='items'),
    path('app/suppliers/', views.suppliers_view, name='suppliers'),
    path('app/customers/', views.customers_view, name='customers'),
    path('app/goods-in/', views.goods_in_view, name='goods_in'),
    path('app/goods-out/', views.goods_out_view, name='goods_out'),
    path('app/spoilage/', views.spoil_damage_view, name='spoilage'),

    path('app/payments/', views.payments_view, name='payments'),
    path('app/reports/', views.reports_view, name='reports'),

    path('app/profile/', views.profile_view, name='profile'),

]