from django.urls import path
from . import views



#
# Profile related views
#

from .profileviews import profile_view, update_profile, update_pwd, update_company

urlpatterns = [
    path('', views.home, name='home'),
    path('t', views.temp, name='temp'),


    path('login/', views.login_view, name='login'),
    path('register/', views.contactus_view, name='register'),
    path('signup/', views.contactus_view, name='register'),

    path("login/api/", views.login_api, name="login_api"),
    path("register/api/", views.contactus_api, name="register_api"),
    path("logout/api/", views.logout_api, name="logout_api"),


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

    path('app/profile/', profile_view, name='profile'),
    path('update-profile/api/', update_profile, name='update_profile'),
    path('update-pwd/api/', update_pwd, name='update_pwd'),
    path('update-company/api/', update_company, name='update_company'),

]