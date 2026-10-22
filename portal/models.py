"""Patient portal: a patient signs in with an ordinary (free Client) account and links it to their treatment record with a
one-time code that their physio generates, plus their date of birth. See docs/PORTAL.md.

The patient code printed on records (PAT-2026...) is NOT used to sign in: it is guessable and appears on paperwork.
"""
import datetime
import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # no 0/O, 1/I/L: easy to read out loud
CODE_LENGTH = 8
INVITE_DAYS = 7
MAX_ATTEMPTS_PER_INVITE = 5


def hash_code(code):
    clean = ''.join(c for c in str(code).upper() if c.isalnum())
    return hashlib.sha256(f'{settings.SECRET_KEY}:portal:{clean}'.encode()).hexdigest()


def make_code():
    raw = ''.join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return raw[:4] + '-' + raw[4:]


class PortalInvite(models.Model):
    """A one-time code a professional creates for a patient. Only a hash is stored: the code is shown once, when created."""
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='portal_invites')
    created_by = models.ForeignKey('accounts.ProfessionalProfile', null=True, on_delete=models.SET_NULL, related_name='+')
    code_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def issue(cls, patient, professional):
        """Replace any open code with a fresh one. Returns (invite, plain_code)."""
        cls.objects.filter(patient=patient, used_at__isnull=True).delete()
        code = make_code()
        invite = cls.objects.create(patient=patient, created_by=professional, code_hash=hash_code(code),
                                    expires_at=timezone.now() + datetime.timedelta(days=INVITE_DAYS))
        return invite, code

    @property
    def is_open(self):
        return self.used_at is None and self.expires_at > timezone.now() and self.failed_attempts < MAX_ATTEMPTS_PER_INVITE


class PatientLink(models.Model):
    """A portal account that may see one patient's shared treatment information. One patient has at most one portal account;
    one account (e.g. a parent) may link several patients."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='patient_links')
    patient = models.OneToOneField('accounts.Patient', on_delete=models.CASCADE, related_name='portal_link')
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['linked_at']

    def __str__(self):
        return f'{self.user} -> {self.patient}'
