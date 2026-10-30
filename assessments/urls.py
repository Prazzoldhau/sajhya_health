from django.urls import path

from . import views

app_name = 'assessments'

urlpatterns = [
    path('patients/<int:pk>/new/', views.choose, name='choose'),
    path('patients/<int:pk>/fill/', views.fill, name='fill'),
    path('patients/<int:pk>/forms/<int:form_id>/', views.clinical_fill, name='clinical-fill'),
    path('records/<int:record_id>/', views.clinical_detail, name='clinical-detail'),
    path('records/<int:record_id>/delete/', views.clinical_delete, name='clinical-delete'),
    path('sessions/<int:session_id>/', views.detail, name='detail'),
    path('sessions/<int:session_id>/delete/', views.delete, name='delete'),
]
