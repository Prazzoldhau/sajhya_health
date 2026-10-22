from django.urls import path

from . import views

app_name = 'profiles'

urlpatterns = [
    path('aids/search/', views.aid_search, name='aid-search'),
    path('medicines/search/', views.medicine_search, name='medicine-search'),
    path('patients/<int:pk>/general/', views.standing_save, name='standing-save'),
    path('patients/<int:pk>/<str:section>/add/', views.entry_add, name='add'),
    path('patients/<int:pk>/<str:section>/<int:entry_id>/delete/', views.entry_delete, name='delete'),
    path('patients/<int:pk>/medicine/<int:entry_id>/status/', views.medicine_status, name='medicine-status'),
    path('patients/<int:pk>/aids/<int:entry_id>/status/', views.aid_status, name='aid-status'),
    path('patients/<int:pk>/labs/<int:entry_id>/result/', views.lab_result, name='lab-result'),
    path('patients/<int:pk>/labs/<int:entry_id>/status/', views.lab_status, name='lab-status'),
    path('patients/<int:pk>/labs/<int:entry_id>/report/', views.lab_report, name='lab-report'),
]
