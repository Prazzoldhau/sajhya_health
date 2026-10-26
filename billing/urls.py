from django.urls import path

from . import views

app_name = 'billing'

urlpatterns = [
    path('', views.billing, name='billing'),
    path('patient/<int:patient_id>/bill/', views.patient_bill, name='patient-bill'),
    path('patient/<int:patient_id>/advance/', views.advance_add, name='advance-add'),
    path('patient/<int:patient_id>/advance/refund/', views.advance_refund, name='advance-refund'),
    path('entry/save/', views.entry_save, name='entry-create'),
    path('entry/<int:pk>/save/', views.entry_save, name='entry-edit'),
    path('entry/<int:pk>/payment/', views.entry_payment, name='entry-payment'),
    path('entry/<int:pk>/invoice/', views.invoice, name='invoice'),
    path('entry/<int:pk>/invoice.pdf', views.invoice_pdf, name='invoice-pdf'),
    path('entry/<int:pk>/invoice/email/', views.invoice_email, name='invoice-email'),
    path('invoice/<str:token>/', views.invoice_public, name='invoice-public'),
    path('entry/<int:pk>/correct/', views.entry_correct, name='entry-correct'),
    path('entry/<int:pk>/cancel/', views.entry_cancel, name='entry-cancel'),
    path('entry/<int:pk>/restore/', views.entry_restore, name='entry-restore'),
    path('entry/<int:pk>/delete/', views.entry_delete, name='entry-delete'),
    # patient packages (1 / 2 / 3 / 4 weeks)
    path('advances/', views.advances, name='advances'),
    path('packages/', views.packages, name='packages'),
    path('packages/create/', views.package_create, name='package-create'),
    path('packages/<int:pk>/payment/', views.package_payment, name='package-payment'),
    path('packages/<int:pk>/cancel/', views.package_cancel, name='package-cancel'),
]
