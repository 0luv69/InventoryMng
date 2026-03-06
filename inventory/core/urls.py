from django.urls import path

from .all_views import supplier_views, profile_views, customer_views, item_views, goodsin_views, goodsout_views, payment_views
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


        # ── Customer APIs ──
    path('app/customers/', customer_views.customers_page, name='customers'),
    path('api/customers/list/', customer_views.customer_list_api, name='customer_list_api'),
    path('api/customers/create/', customer_views.customer_create_api, name='customer_create_api'),
    path('api/customers/update/', customer_views.customer_update_api, name='customer_update_api'),
    path('api/customers/delete/', customer_views.customer_delete_api, name='customer_delete_api'),


            # ── Item APIs ──
    path('app/items/', item_views.items_page, name='items'),
    path('api/items/list/', item_views.item_list_api, name='item_list_api'),
    path('api/items/create/', item_views.item_create_api, name='item_create_api'),
    path('api/items/update/', item_views.item_update_api, name='item_update_api'),
    path('api/items/delete/', item_views.item_delete_api, name='item_delete_api'),



            # ── Goods-In (Purchase Invoice) APIs ──
    path('api/goodsin/list/',               goodsin_views.goodsin_list_api,         name='goodsin_list_api'),
    path('api/goodsin/detail/<int:pk>/',    goodsin_views.goodsin_detail_api,       name='goodsin_detail_api'),
    path('api/goodsin/create/',             goodsin_views.goodsin_create_api,       name='goodsin_create_api'),
    path('api/goodsin/update/<int:pk>/',    goodsin_views.goodsin_update_api,       name='goodsin_update_api'),
    path('api/goodsin/void/<int:pk>/',      goodsin_views.goodsin_void_api,         name='goodsin_void_api'),
    path('api/goodsin/bulk-void/',          goodsin_views.goodsin_bulk_void_api,    name='goodsin_bulk_void_api'),

        # ── Goods-In Helper APIs ──
    path('api/goodsin/helpers/items/',      goodsin_views.goodsin_helpers_items,    name='goodsin_helpers_items'),
    path('api/goodsin/helpers/suppliers/',   goodsin_views.goodsin_helpers_suppliers, name='goodsin_helpers_suppliers'),
    path('api/goodsin/helpers/users/',      goodsin_views.goodsin_helpers_users,    name='goodsin_helpers_users'),


         # ── Goods-Out (Sale Invoice) APIs ──
    path('api/goodsout/list/',              goodsout_views.goodsout_list_api,       name='goodsout_list_api'),
    path('api/goodsout/detail/<int:pk>/',   goodsout_views.goodsout_detail_api,     name='goodsout_detail_api'),
    path('api/goodsout/create/',            goodsout_views.goodsout_create_api,     name='goodsout_create_api'),
    path('api/goodsout/update/<int:pk>/',   goodsout_views.goodsout_update_api,     name='goodsout_update_api'),
    path('api/goodsout/void/<int:pk>/',     goodsout_views.goodsout_void_api,       name='goodsout_void_api'),
    path('api/goodsout/bulk-void/',         goodsout_views.goodsout_bulk_void_api,  name='goodsout_bulk_void_api'),
    path('api/goodsout/helpers/items/',     goodsout_views.goodsout_helpers_items,  name='goodsout_helpers_items'),
    path('api/goodsout/helpers/customers/', goodsout_views.goodsout_helpers_customers, name='goodsout_helpers_customers'),
    path('api/goodsout/helpers/users/',     goodsout_views.goodsout_helpers_users,  name='goodsout_helpers_users'),



            # ── Payment APIs ──
    path('api/payments/list/',              payment_views.payment_list_api,         name='payment_list_api'),
    path('api/payments/detail/<int:pk>/',   payment_views.payment_detail_api,       name='payment_detail_api'),
    path('api/payments/create/',            payment_views.payment_create_api,       name='payment_create_api'),
    path('api/payments/update/<int:pk>/',   payment_views.payment_update_api,       name='payment_update_api'),
    path('api/payments/void/<int:pk>/',     payment_views.payment_void_api,         name='payment_void_api'),
    path('api/payments/bulk-void/',         payment_views.payment_bulk_void_api,    name='payment_bulk_void_api'),
    path('api/payments/helpers/customers/',         payment_views.payment_helpers_customers,        name='payment_helpers_customers'),
    path('api/payments/helpers/suppliers/',          payment_views.payment_helpers_suppliers,         name='payment_helpers_suppliers'),
    path('api/payments/helpers/users/',              payment_views.payment_helpers_users,             name='payment_helpers_users'),
    path('api/payments/helpers/sale-invoices/',      payment_views.payment_helpers_sale_invoices,     name='payment_helpers_sale_invoices'),
    path('api/payments/helpers/purchase-invoices/',  payment_views.payment_helpers_purchase_invoices, name='payment_helpers_purchase_invoices'),

]