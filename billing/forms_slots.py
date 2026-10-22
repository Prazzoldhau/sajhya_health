from django import forms


class SlotOrderForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=500, label='How many extra patients?')
