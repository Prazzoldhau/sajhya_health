from django.urls import path

from . import views

app_name = 'assessments'

urlpatterns = [
    path('patients/<int:pk>/new/', views.choose, name='choose'),
    path('patients/<int:pk>/fill/', views.fill, name='fill'),
    path('sessions/<int:session_id>/', views.detail, name='detail'),
    path('sessions/<int:session_id>/delete/', views.delete, name='delete'),
]
