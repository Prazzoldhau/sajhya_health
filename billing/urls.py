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
    path('entry/<int:pk>/invoice.png', views.invoice_png, name='invoice-png'),
    path('entry/<int:pk>/invoice.pdf', views.invoice_pdf, name='invoice-pdf'),
    path('entry/<int:pk>/invoice/email/', views.invoice_email, name='invoice-email'),
    path('invoice/<str:token>/', views.invoice_public, name='invoice-public'),
    path('entry/<int:pk>/correct/', views.entry_correct, name='entry-correct'),
    path('entry/<int:pk>/cancel/', views.entry_cancel, name='entry-cancel'),
    path('entry/<int:pk>/restore/', views.entry_restore, name='entry-restore'),
    path('entry/<int:pk>/delete/', views.entry_delete, name='entry-delete'),
    # patient packages (1 / 2 / 3 / 4 weeks)
    path('services/<int:pk>/stock/', views.stock_adjust, name='stock-adjust'),
    path('services/', views.services, name='services'),
    path('services/seed/', views.services_seed, name='services-seed'),
    path('services/<int:pk>/save/', views.service_save, name='service-save'),
    path('services/<int:pk>/delete/', views.service_delete, name='service-delete'),
    path('sheet/', views.sheet, name='sheet'),
    path('export.xlsx', views.export_xlsx, name='export-xlsx'),
    path('export.csv', views.export_csv, name='export-csv'),
    path('advances/', views.advances, name='advances'),
    path('packages/', views.packages, name='packages'),
    path('packages/create/', views.package_create, name='package-create'),
    path('packages/<int:pk>/payment/', views.package_payment, name='package-payment'),
    path('packages/<int:pk>/use/', views.package_use, name='package-use'),
    path('packages/<int:pk>/sessions/<int:entry_id>/undo/', views.package_session_undo, name='package-session-undo'),
    path('packages/<int:pk>/invoice/', views.package_invoice, name='package-invoice'),
    path('packages/<int:pk>/invoice.pdf', views.package_invoice_pdf, name='package-invoice-pdf'),
    path('packages/<int:pk>/invoice/email/', views.package_invoice_email, name='package-invoice-email'),
    path('package-invoice/<str:token>/', views.package_invoice_public, name='package-invoice-public'),
    path('packages/payments/<int:pk>/receipt/', views.package_receipt, name='package-receipt'),
    path('packages/payments/<int:pk>/receipt.pdf', views.package_receipt_pdf, name='package-receipt-pdf'),
    path('packages/payments/<int:pk>/receipt/email/', views.package_receipt_email, name='package-receipt-email'),
    path('package-receipt/<str:token>/', views.package_receipt_public, name='package-receipt-public'),
    path('packages/<int:pk>/cancel/', views.package_cancel, name='package-cancel'),
]
