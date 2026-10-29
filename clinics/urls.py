from django.urls import path

from . import desk, views

app_name = 'clinics'

urlpatterns = [
    path('', views.hub, name='hub'),
    path('desk/', desk.desk, name='desk'),
    path('my-schedule/', views.my_schedule, name='my-schedule'),
    path('desk/register/', desk.register_patient, name='desk-register'),
    path('desk/treatment/save/', desk.session_create, name='desk-session-create'),
    path('desk/treatment/search/', desk.treatment_search, name='desk-treatment-search'),
    path('desk/appointments/new/', desk.appt_create, name='desk-appt-create'),
    path('desk/appointments/<int:appt_id>/edit/', desk.appt_edit, name='desk-appt-edit'),
    path('desk/appointments/<int:appt_id>/cancel/', desk.appt_cancel, name='desk-appt-cancel'),
    path('desk/billing/new/', desk.bill_create, name='desk-bill-create'),
    path('desk/billing/export.xlsx', desk.bill_export, name='desk-bill-export'),
    path('desk/billing/<int:entry_id>/payment/', desk.bill_payment, name='desk-bill-payment'),
    path('desk/billing/<int:entry_id>/invoice.pdf', desk.bill_pdf, name='desk-bill-pdf'),
    path('desk/queue/add/', desk.queue_add, name='desk-queue-add'),
    path('desk/queue/<int:entry_id>/action/', desk.queue_action, name='desk-queue-action'),
    path('desk/patients/search/', desk.patient_search, name='desk-patient-search'),
    path('register/', views.register, name='register'),
    path('new/', views.clinic_create, name='create'),
    path('physios/search/', views.physio_search, name='physio-search'),
    path('invitations/<int:member_id>/respond/', views.invitation_respond, name='invitation-respond'),
    path('<int:pk>/', views.clinic_detail, name='detail'),
    path('<int:pk>/update/', views.clinic_update, name='update'),
    path('<int:pk>/login/', views.clinic_login, name='login'),
    path('<int:pk>/leave/', views.leave, name='leave'),
    path('<int:pk>/team/invite/', views.member_invite, name='invite'),
    path('<int:pk>/team/staff/', views.staff_add, name='staff-add'),
    path('<int:pk>/team/<int:member_id>/login/', views.staff_login, name='staff-login'),
    path('<int:pk>/team/<int:member_id>/departments/', views.member_departments, name='member-departments'),
    path('<int:pk>/team/<int:member_id>/remove/', views.member_remove, name='member-remove'),
    path('<int:pk>/queue/add/', views.queue_add, name='queue-add'),
    path('<int:pk>/patients/search/', views.patient_search, name='patient-search'),
    path('<int:pk>/queue/<int:entry_id>/action/', views.queue_action, name='queue-action'),
]
