from django.urls import path
from . import views

app_name = 'frontend' # This allows us to use frontend:dashboard

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),

    path('settings/quick-add-category/', views.QuickAddCategoryView.as_view(), name='quick_add_category'),
    path('settings/quick-add-unit/', views.QuickAddUnitView.as_view(), name='quick_add_unit'),
    path('settings/quick-add-tier/', views.QuickAddPriceTierView.as_view(), name='quick_add_tier'),
    
    # Items
    path('items/', views.ItemsView.as_view(), name='items'),
    path('items/table/', views.ItemsTableView.as_view(), name='items_table'),
    path('items/form/', views.ItemFormView.as_view(), name='item_form'),
    path('items/save/', views.ItemSaveView.as_view(), name='item_save'),
    path('items/delete/<int:item_id>/', views.ItemDeleteView.as_view(), name='item_delete'),



    # Goods In
    path('goods-in/', views.GoodsInView.as_view(), name='goods_in'),
    path('goods-in/table/', views.GoodsInTableView.as_view(), name='goods_in_table'),
    path('goods-in/form/', views.GoodsInFormView.as_view(), name='goods_in_form'),
    path('goods-in/save/', views.GoodsInSaveView.as_view(), name='goods_in_save'),
    path('goods-in/void/<int:invoice_id>/', views.GoodsInVoidView.as_view(), name='goods_in_void'),



    # Goods Out
    path('goods-out/', views.GoodsOutView.as_view(), name='goods_out'),
    path('goods-out/table/', views.GoodsOutTableView.as_view(), name='goods_out_table'),
    path('goods-out/form/', views.GoodsOutFormView.as_view(), name='goods_out_form'),
    path('goods-out/save/', views.GoodsOutSaveView.as_view(), name='goods_out_save'),
    path('goods-out/void/<int:invoice_id>/', views.GoodsOutVoidView.as_view(), name='goods_out_void'),


    path('parties/', views.PartiesView.as_view(), name='parties'),
    path('spoilage/', views.SpoilageView.as_view(), name='spoilage'),
    path('payments/', views.PaymentsView.as_view(), name='payments'),
    path('reports/', views.ReportsView.as_view(), name='reports'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
]