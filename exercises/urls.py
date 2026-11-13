from django.urls import path

from . import views

app_name = 'exercises'

urlpatterns = [
    path('', views.library, name='library'),
    path('<int:pk>/json/', views.exercise_detail, name='detail'),
    path('search/', views.exercise_search, name='search'),
    path('prescribe/', views.prescribe, name='prescribe'),
    path('prescriptions/<int:pk>/action/', views.prescription_action, name='prescription-action'),
    path('prescriptions/<int:pk>/send/', views.send, name='send'),
    path('prescriptions/<int:pk>/programme.pdf', views.handout_pdf, name='pdf'),
    path('prescriptions/<int:pk>/email/', views.send_email, name='email'),
    path('shared/<str:token>/', views.public, name='public'),
]
