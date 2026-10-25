from django.urls import path

from . import views

app_name = 'billing'

urlpatterns = [
    path('', views.billing, name='billing'),
    path('patient/<int:patient_id>/bill/', views.patient_bill, name='patient-bill'),
    path('entry/save/', views.entry_save, name='entry-create'),
    path('entry/<int:pk>/save/', views.entry_save, name='entry-edit'),
    path('entry/<int:pk>/payment/', views.entry_payment, name='entry-payment'),
    path('entry/<int:pk>/delete/', views.entry_delete, name='entry-delete'),
    # patient packages (1 / 2 / 3 / 4 weeks)
    path('packages/', views.packages, name='packages'),
    path('packages/create/', views.package_create, name='package-create'),
    path('packages/<int:pk>/payment/', views.package_payment, name='package-payment'),
    path('packages/<int:pk>/cancel/', views.package_cancel, name='package-cancel'),
]
