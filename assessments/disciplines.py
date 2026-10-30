"""Which assessments a person sees: each belongs to a discipline, and people see their own (plus the general ones).

A physiotherapist sees physiotherapy assessments and never the occupational therapy ones, an occupational therapist the reverse. Someone who is not
one specific discipline (the clinic's own login, a doctor...) may use any, and switches between them on the page.
"""
DISCIPLINE_CHOICES = [('physio', 'Physiotherapy'), ('ot', 'Occupational therapy'), ('speech', 'Speech therapy'), ('behaviour', 'Behaviour therapy'),
                      ('general', 'General (every discipline)')]
LABELS = dict(DISCIPLINE_CHOICES)
SPECIFIC = [key for key, _ in DISCIPLINE_CHOICES if key != 'general']


def discipline_of(profile):
    """The discipline a professional works in, from their profession; None when it is not one of ours (clinic login, doctor, nurse...)."""
    profession = getattr(getattr(profile, 'account', None), 'profession', None)
    name = (getattr(profession, 'name', '') or '').lower()
    for key, words in (('physio', ('physio',)), ('ot', ('occupational',)), ('speech', ('speech',)), ('behaviour', ('behav',))):
        if any(word in name for word in words):
            return key
    return None


def allowed(profile):
    """The specific disciplines this person may see and use."""
    own = discipline_of(profile)
    return [own] if own else list(SPECIFIC)


def visible_filter(disciplines):
    """The values of an assessment's discipline that are visible for these allowed disciplines (general is visible to all)."""
    return list(disciplines) + ['general']


def chosen(profile, requested):
    """The discipline being worked in: the requested one when allowed, else their own, else the first allowed."""
    options = allowed(profile)
    return requested if requested in options else options[0]
