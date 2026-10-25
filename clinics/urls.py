from django.urls import path

from . import views

app_name = 'clinics'

urlpatterns = [
    path('', views.hub, name='hub'),
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
    path('<int:pk>/team/<int:member_id>/remove/', views.member_remove, name='member-remove'),
    path('<int:pk>/queue/add/', views.queue_add, name='queue-add'),
    path('<int:pk>/patients/search/', views.patient_search, name='patient-search'),
    path('<int:pk>/queue/<int:entry_id>/action/', views.queue_action, name='queue-action'),
]
