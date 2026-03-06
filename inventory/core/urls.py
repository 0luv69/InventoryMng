from django.urls import path

from .all_views import supplier_views, profile_views
from .all_views import main as main_views

urlpatterns = [
    path('', main_views.home, name='home'),
    path('t', main_views.temp, name='temp'),


    path('login/', main_views.login_view, name='login'),
    path('register/', main_views.contactus_view, name='register'),
    path('signup/', main_views.contactus_view, name='register'),

    path("login/api/", main_views.login_api, name="login_api"),
    path("register/api/", main_views.contactus_api, name="register_api"),
    path("logout/api/", main_views.logout_api, name="logout_api"),


    path('app/dashboard/', main_views.dashboard, name='dashboard'),
    path('app/', main_views.app_home, name='app_home'),

    path('app/items/', main_views.items_view, name='items'),
    path('app/customers/', main_views.customers_view, name='customers'),
    path('app/goods-in/', main_views.goods_in_view, name='goods_in'),
    path('app/goods-out/', main_views.goods_out_view, name='goods_out'),
    path('app/spoilage/', main_views.spoil_damage_view, name='spoilage'),

    path('app/payments/', main_views.payments_view, name='payments'),
    path('app/reports/', main_views.reports_view, name='reports'),


        # ── Profile APIs ──
    path('app/profile/', profile_views.profile_view, name='profile'),
    path('update-profile/api/', profile_views.update_profile, name='update_profile'),
    path('update-pwd/api/', profile_views.update_pwd, name='update_pwd'),
    path('update-company/api/', profile_views.update_company, name='update_company'),



        # ── Supplier APIs ──                                              
    path('app/suppliers/', supplier_views.suppliers_page, name='suppliers'),
    path('api/suppliers/list/', supplier_views.supplier_list_api, name='supplier_list_api'),
    path('api/suppliers/create/', supplier_views.supplier_create_api, name='supplier_create_api'),
    path('api/suppliers/update/', supplier_views.supplier_update_api, name='supplier_update_api'),
    path('api/suppliers/delete/', supplier_views.supplier_delete_api, name='supplier_delete_api'),
]