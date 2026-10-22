from django.urls import path

from . import views

app_name = 'soapnotes'

urlpatterns = [
    path('patients/<int:pk>/new/', views.new, name='new'),
    path('<int:note_id>/', views.detail, name='detail'),
    path('<int:note_id>/edit/', views.edit, name='edit'),
    path('<int:note_id>/addendum/', views.addendum, name='addendum'),
    path('<int:note_id>/delete/', views.delete, name='delete'),
]
