from django.urls import path

from . import views

app_name = 'lab'

urlpatterns = [
    path('', views.lab_tests, name='tests'),
    path('search/', views.lab_search, name='search'),
    path('test/<int:test_id>/', views.lab_test_detail, name='test-detail'),
    path('panel/<int:panel_id>/', views.lab_panel_detail, name='panel-detail'),
    path('booked/<str:request_number>/', views.lab_order_success, name='order-success'),
]
