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

]