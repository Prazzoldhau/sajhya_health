from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.urls import path
from django.views.generic import TemplateView

from . import appointments, notices, plans, report_views, settings_views, treatments, views
from .forms import StyledAuthenticationForm
from . import auth_views as password_views

app_name = 'accounts'

urlpatterns = [
    path('package/', views.package, name='package'),
    path('signup/client/', views.signup, {'account_type': 'client'}, name='signup-client'),
    path('signup/<str:account_type>/', views.select_type, name='select-type'),
    path('signup/<str:account_type>/<int:subtype_id>/', views.signup, name='signup'),
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html', redirect_authenticated_user=True, authentication_form=StyledAuthenticationForm), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('professional/step/<int:step>/', views.professional_step, name='professional-step'),
    path('professional/document/<str:field>/', views.professional_document, name='professional-document'),
    path('professional/<int:profile_id>/document/<str:field>/', views.professional_document, name='professional-document-staff'),
    path('review/', views.review_list, name='review-list'),
    path('review/<int:profile_id>/', views.review_detail, name='review-detail'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('messages/', notices.messages_page, name='messages'),
    path('messages/whatsapp-number/', notices.whatsapp_number_save, name='whatsapp-number'),
    path('messages/send/', notices.notice_send, name='notice-send'),
    path('messages/custom/add/', notices.custom_add, name='custom-add'),
    path('messages/custom/<str:key>/delete/', notices.custom_delete, name='custom-delete'),
    path('messages/<str:key>/save/', notices.message_save, name='message-save'),
    path('messages/<str:key>/reset/', notices.message_reset, name='message-reset'),
    path('reports/', report_views.reports, name='reports'),
    path('settings/', settings_views.settings_page, name='settings'),
    path('profile-photo/', views.profile_picture, name='profile-picture'),
    path('patients/', views.patient_list, name='patients'),
    path('patients/add/', views.patient_add, name='patient-add'),
    path('patients/<int:pk>/', views.patient_detail, name='patient-detail'),
    path('patients/<int:pk>/edit/', views.patient_edit, name='patient-edit'),
    path('patients/<int:pk>/photo/<str:version>/', views.patient_photo, name='patient-photo'),
    path('patients/<int:pk>/photo/', views.patient_photo_update, name='patient-photo-update'),
    path('patients/treatments/search/', treatments.treatment_search, name='treatment-search'),
    path('patients/<int:pk>/visit/add/', views.patient_visit_add, name='patient-visit-add'),
    path('patients/<int:pk>/notes/', views.patient_notes, name='patient-notes'),
    path('patients/<int:pk>/next-visit/', views.patient_next_visit, name='patient-next-visit'),
    path('icd10/search/', views.icd10_search, name='icd10-search'),
    path('appointments/', appointments.appointments, name='appointments'),
    path('appointments/patients/', appointments.patient_search, name='appointment-patient-search'),
    path('appointments/create/', appointments.appointment_create, name='appointment-create'),
    path('appointments/block/', appointments.block_create, name='block-create'),
    path('appointments/<int:pk>/edit/', appointments.appointment_edit, name='appointment-edit'),
    path('appointments/<int:pk>/action/', appointments.appointment_action, name='appointment-action'),
    path('tasks/add/', appointments.task_add, name='task-add'),
    path('tasks/<int:pk>/toggle/', appointments.task_toggle, name='task-toggle'),
    path('tasks/<int:pk>/delete/', appointments.task_delete, name='task-delete'),
    path('plans/', plans.plans_list, name='plans'),
    path('plans/<int:pk>/', plans.plan_detail, name='plan-detail'),
    path('plans/<int:pk>/edit/', plans.plan_builder, name='plan-edit'),
    path('plans/<int:pk>/save/', plans.plan_save, name='plan-save'),
    path('plans/<int:pk>/action/', plans.plan_action, name='plan-action'),
    path('patients/<int:patient_pk>/plan/new/', plans.plan_builder, name='plan-new'),
    path('patients/<int:patient_pk>/plan/create/', plans.plan_save, name='plan-create'),
    path('password/forgot/', password_views.ThrottledPasswordResetView.as_view(), name='password-reset'),
    path('password/forgot/sent/', TemplateView.as_view(template_name='accounts/password_reset_done.html'), name='password-reset-done'),
    path('password/reset/<uidb64>/<token>/', password_views.ResetConfirmView.as_view(), name='password-reset-confirm'),
    path('password/reset/done/', TemplateView.as_view(template_name='accounts/password_reset_complete.html'), name='password-reset-complete'),
    path('password/change/', login_required(password_views.ChangePasswordView.as_view()), name='password-change'),
    path('password/change/done/', login_required(TemplateView.as_view(template_name='accounts/password_change_done.html')), name='password-change-done'),
    path('welcome/', views.welcome, name='welcome'),
]
