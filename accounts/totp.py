"""Time-based one-time codes (RFC 6238) for two-step sign-in, with Python's standard library only: no extra package to install.

An authenticator app (Google Authenticator, Microsoft Authenticator, Authy, FreeOTP...) holds a secret and shows a six digit code that changes every
30 seconds. The server holds the same secret and checks the code, allowing one step either side for clocks that differ a little. A code that has been
used cannot be used again.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1


def new_secret():
    """A random 160-bit secret in base32 (what authenticator apps expect), 32 characters."""
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii')


def _code(secret, step):
    key = base64.b32decode(secret.replace(' ', '').upper() + '=' * (-len(secret.replace(' ', '')) % 8))
    digest = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(value).zfill(DIGITS)


def current_step(now=None):
    return int((now if now is not None else time.time()) // STEP)


def verify(secret, code, last_step=0, now=None):
    """The time step the code belongs to when it is right and not used before, else None."""
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(code) != DIGITS:
        return None
    step = current_step(now)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if candidate > last_step and hmac.compare_digest(_code(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(account_name, secret, issuer='Sajhya Health'):
    return f'otpauth://totp/{quote(issuer)}:{quote(account_name)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}'


def grouped(secret):
    """The secret in groups of four, easier to type: ABCD EFGH ..."""
    return ' '.join(secret[i:i + 4] for i in range(0, len(secret), 4))


def new_recovery_codes(count=10):
    """Ten one-time codes like 'k3m9-x7qp-2d8f'. Shown once; only their hashes are kept."""
    alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
    return ['-'.join(''.join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)) for _ in range(count)]


def hash_recovery(code):
    clean = ''.join(ch for ch in str(code).lower() if ch.isalnum())
    return hashlib.sha256(f'recovery:{clean}'.encode()).hexdigest()
