from django.urls import path

from . import views

app_name = 'portal'

urlpatterns = [
    path('', views.home, name='home'),
    path('plan/', views.plan, name='plan'),
    path('exercises/', views.exercises, name='exercises'),
    path('advice/', views.advice, name='advice'),
    path('services/', views.services, name='services'),
    path('orders/', views.orders, name='orders'),
    path('lab/', views.lab_bookings, name='lab'),
    path('claim/', views.claim, name='claim'),
    path('settings/', views.settings_page, name='settings'),
    path('link/', views.link, name='link'),
    path('patients/<int:pk>/exercises/<int:item_id>/done/', views.exercise_done, name='exercise-done'),
    path('patients/<int:pk>/exercises/<int:item_id>/feedback/', views.exercise_feedback, name='exercise-feedback'),
    path('patients/<int:pk>/unlink/', views.unlink, name='unlink'),
    path('invite/<int:pk>/', views.invite, name='invite'),
    path('revoke/<int:pk>/', views.revoke, name='revoke'),
]
