"""The parts of the workspace a clinic can switch on, one by one (staff set them per clinic in the admin).

Patients, the queue, the team and settings are always there. Everything below can be left out of a clinic's plan: its own login then loses
the menu item and the pages, and its front desk loses the matching tab. A physiotherapist's personal workspace is never restricted.
"""
# (key, name, what it gives, URL prefixes it covers)
MODULES = [
    ('appointments', 'Appointments', 'Calendar, bookings, departments and to-dos', ('/accounts/appointments/', '/accounts/tasks/')),
    ('billing', 'Billing & accounts', 'Bills, payments, advances, packages, price list and Excel exports', ('/billing/',)),
    ('assessments', 'Assessments & SOAP notes', 'Clinical assessments and SOAP notes', ('/assessments/', '/soapnotes/')),
    ('plans', 'Treatment plans & exercises', 'Treatment plans and the exercise library', ('/accounts/plans/', '/exercises/')),
    ('messages', 'Messages & notices', 'WhatsApp / Viber messages and notices to patients', ('/accounts/messages/',)),
    ('reports', 'Reports', 'Practice reports and exports', ('/accounts/reports/',)),
]
KEYS = [key for key, *_ in MODULES]
NAMES = {key: name for key, name, *_ in MODULES}
PREFIXES = tuple(prefix for *_, prefixes in MODULES for prefix in prefixes)
# front-desk permissions that belong to a module
PERMISSION_MODULES = {'billing': 'billing', 'schedule': 'appointments', 'appointments': 'appointments'}


def default_modules():
    """A new clinic starts with every module on; staff switch off what its plan does not include."""
    return list(KEYS)


def module_for_path(path):
    for key, _name, _what, prefixes in MODULES:
        if path.startswith(prefixes):
            return key
    return None


def disabled_for(profile):
    """Module keys switched off for this workspace: only a clinic's own login can have any."""
    clinic = getattr(profile, 'clinic_workspace', None) if profile is not None else None
    if clinic is None:
        return []
    return [key for key in KEYS if key not in (clinic.modules or [])]
