from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .access import first_error, workspace_context, workspace_profile
from billing.forms_slots import SlotOrderForm
from billing.models import PatientAllowance, SlotOrder

from .forms import SettingsEmailForm, SettingsPracticeForm, SettingsProfileForm

TABS = [('profile', 'My profile'), ('practice', 'Practice'), ('plan', 'Plan & usage'), ('account', 'Account & security')]


@login_required
def settings_page(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    tab = request.GET.get('tab') if request.GET.get('tab') in dict(TABS) else 'profile'
    forms_by_tab = {
        'profile': lambda data=None, files=None: SettingsProfileForm(data, files, instance=profile),
        'practice': lambda data=None, files=None: SettingsPracticeForm(data, instance=profile),
        'account': lambda data=None, files=None: SettingsEmailForm(data, user=request.user),
        'plan': lambda data=None, files=None: SlotOrderForm(data),
    }
    if request.method == 'POST':
        tab = request.POST.get('tab') if request.POST.get('tab') in dict(TABS) else 'profile'
        form = forms_by_tab[tab](request.POST, request.FILES)
        if form.is_valid():
            if tab == 'plan':
                allowance = PatientAllowance.for_profile(profile)
                quantity = form.cleaned_data['quantity']
                SlotOrder.objects.create(professional=profile, quantity=quantity, rate=allowance.rate, amount=allowance.rate * quantity)
                messages.success(request, f'Order placed: {quantity} extra patient slot{"s" if quantity != 1 else ""}, NPR {allowance.rate * quantity:,.0f}. Our team will contact you to collect payment and add the slots.')
                return redirect(f"{request.path}?tab=plan")
            if tab == 'account':
                request.user.email = form.cleaned_data['email']
                request.user.save(update_fields=['email'])
            else:
                form.save()
            messages.success(request, 'Settings saved.')
            return redirect(f'{request.path}?tab={tab}')
        messages.error(request, first_error(form))
    else:
        form = forms_by_tab[tab]()
    context = workspace_context(request.user, profile)
    context.update({'active': 'settings', 'tab': tab, 'tabs': TABS, 'form': form})
    if tab == 'plan':
        context.update({'allowance': PatientAllowance.for_profile(profile), 'slot_orders': profile.slot_orders.all()[:10]})
    return render(request, 'accounts/settings.html', context)
