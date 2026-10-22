"""Form widgets used across the workspace forms (native date / time pickers with the format Django expects back)."""
from django import forms


def date_widget():
    return forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


def time_widget():
    return forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')


def datetime_widget():
    return forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')
