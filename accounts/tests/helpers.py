import datetime
import shutil
import tempfile
from contextlib import contextmanager

from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import Account, Patient, ProfessionalProfile, Profession

PASSWORD = 'Gr33n!Health-99'


def make_professional(username='pro', status='approved', completed_step=4, staff=False, **profile_kwargs):
    """A professional account (user + account + profile). Returns (user, profile)."""
    user = User.objects.create_user(username, f'{username}@example.com', PASSWORD, is_staff=staff)
    account = Account.objects.create(user=user, account_type=Account.PROFESSIONAL, profession=Profession.objects.first())
    defaults = dict(first_name='Asha', last_name='Rai', mobile='9800000000', title='PT', status=status, completed_step=completed_step)
    defaults.update(profile_kwargs)
    return user, ProfessionalProfile.objects.create(account=account, **defaults)


def make_patient(profile, name='Sita Gurung', **kwargs):
    defaults = dict(phone='9841000000', gender='F', date_of_birth=datetime.date(1990, 1, 2))
    defaults.update(kwargs)
    return Patient.objects.create(professional=profile, name=name, **defaults)


def pdf(name='doc.pdf'):
    return SimpleUploadedFile(name, b'%PDF-1.4 test', content_type='application/pdf')


@contextmanager
def private_storage():
    """Send credential uploads to a throwaway folder instead of the real private_uploads/."""
    tmp = tempfile.mkdtemp()
    from profiles.models import LabEntry
    fields = ([ProfessionalProfile._meta.get_field(f) for f in ProfessionalProfile.DOCUMENT_FIELDS]
              + [Patient._meta.get_field('photo'), LabEntry._meta.get_field('report')])
    originals = [f.storage for f in fields]
    for f in fields:
        f.storage = FileSystemStorage(location=tmp)
    try:
        yield tmp
    finally:
        for f, original in zip(fields, originals):
            f.storage = original
        shutil.rmtree(tmp, ignore_errors=True)
