"""
Django settings for the Sajhya Health project.

Configuration comes from the environment (a `.env` file next to manage.py in development).
See `.env.example` for every variable. With DEBUG off, the settings refuse to start unless a real
SECRET_KEY, ALLOWED_HOSTS and DATABASE_URL are provided.
"""

import sys
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
# .env is gitignored - it holds the secrets for this machine.
if (BASE_DIR / '.env').exists():
    environ.Env.read_env(BASE_DIR / '.env')

# Off unless explicitly turned on: a forgotten variable must never leave debug pages open in production.
DEBUG = env.bool('DEBUG', default=False)

_DEV_SECRET = 'django-insecure-dev-only-key-do-not-use-in-production'
SECRET_KEY = env('SECRET_KEY', default=_DEV_SECRET if DEBUG else '')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'] if DEBUG else [])

if not DEBUG:
    if not SECRET_KEY or SECRET_KEY.startswith('django-insecure') or SECRET_KEY in ('change-me', _DEV_SECRET) or len(SECRET_KEY) < 40:
        raise ImproperlyConfigured('Set SECRET_KEY in the environment to a long random value (40+ characters) when DEBUG is off.')
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured('Set ALLOWED_HOSTS (comma separated) when DEBUG is off.')
    if not env('DATABASE_URL', default=''):
        raise ImproperlyConfigured('Set DATABASE_URL when DEBUG is off.')

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'axes',
    'accounts',
    'marketplace',
    'exercises',
    'billing',
    'lab',
    'profiles',
    'assessments',
    'clinics',
    'soapnotes',
    'portal',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'accounts.middleware.VerifiedWorkspaceMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',  # must be last
]

# URL prefixes that belong to the clinical workspace. Professionals whose credentials are not approved are kept out of all
# of them (see accounts/middleware.py). Add the prefix of any new workspace area here.
WORKSPACE_PATH_PREFIXES = [
    '/accounts/dashboard/', '/accounts/patients/', '/accounts/appointments/', '/accounts/plans/', '/accounts/tasks/', '/accounts/reports/', '/accounts/settings/',
    '/accounts/icd10/', '/billing/', '/exercises/', '/profiles/', '/assessments/', '/clinics/', '/soapnotes/', '/lab-tests/search/',
]

ROOT_URLCONF = 'sajhya_health.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'sajhya_health.wsgi.application'


# Database
# MySQL in production (DATABASE_URL=mysql://user:pass@host:3306/db). SQLite is only a development fallback.

_db_config = env.db(default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')
if _db_config['ENGINE'] == 'django.db.backends.mysql':
    _db_config['OPTIONS'] = {'charset': 'utf8mb4', 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"}
    _db_config['CONN_MAX_AGE'] = env.int('DB_CONN_MAX_AGE', default=60)
DATABASES = {'default': _db_config}

# The app's MySQL user normally cannot create a test database, so `manage.py test` runs on in-memory
# SQLite unless TEST_DATABASE_URL says otherwise.
TESTING = 'test' in sys.argv

# Pricing rules (NPR). Professional: the first FREE_PATIENT_LIMIT patients are free, each additional patient costs PATIENT_SLOT_RATE
# (bought in advance as "patient slots"). Clinic: up to CLINIC_MONTHLY_PATIENT_CAP newly enrolled patients per calendar month are
# included; each one above the cap is added as a due at CLINIC_OVERAGE_RATE. All can be overridden per professional / clinic in the admin.
THROTTLE_ENABLED = env.bool('THROTTLE_ENABLED', default=not TESTING)  # per-IP limits on public forms (sajhya_health/throttle.py)
FREE_PATIENT_LIMIT = env.int('FREE_PATIENT_LIMIT', default=10)
PATIENT_SLOT_RATE = env.int('PATIENT_SLOT_RATE', default=200)
CLINIC_MONTHLY_PATIENT_CAP = env.int('CLINIC_MONTHLY_PATIENT_CAP', default=400)
CLINIC_OVERAGE_RATE = env.int('CLINIC_OVERAGE_RATE', default=200)
if TESTING:
    DATABASES = {'default': env.db('TEST_DATABASE_URL', default='sqlite://:memory:')}


# Authentication, with brute-force protection on the login form

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]
AXES_ENABLED = not TESTING  # the lockout test switches it back on
AXES_FAILURE_LIMIT = env.int('LOGIN_FAILURE_LIMIT', default=5)
AXES_COOLOFF_TIME = 0.25  # hours locked out after too many failed logins
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = 'locked.html'
# behind a reverse proxy the client IP arrives in this header (only trust it when you control the proxy)
if env.bool('BEHIND_PROXY', default=False):
    AXES_IPWARE_PROXY_COUNT = 1
    AXES_IPWARE_META_PRECEDENCE_ORDER = ['HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR']

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Reset links work for one hour and once (Django's default is three days)
PASSWORD_RESET_TIMEOUT = 3600

# The reset-request throttle counts in the cache. In production use a file cache so every worker process shares it.
_cache_dir = Path(env('CACHE_DIR', default='').strip() or BASE_DIR / 'cache')
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
if not DEBUG and not ('test' in sys.argv):
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache', 'LOCATION': str(_cache_dir)}}

# The Django admin lives at /admin/ by default; in production set ADMIN_URL to something less guessable, e.g. ADMIN_URL=sajhya-office-7k2/
ADMIN_URL = env('ADMIN_URL', default='admin/').strip('/') + '/'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:welcome'
LOGOUT_REDIRECT_URL = 'landing'


# Internationalization - the clinic runs on Nepal time

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kathmandu'
USE_I18N = True
USE_TZ = True


# Static and media files

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
# Plain (non-hashed) filenames: product and exercise images are referenced by stored path, so a
# hashed-manifest storage would 404 whenever the manifest is stale.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

# Public uploads (profile photos, product photos). Serve /media/ from the web server in production;
# set SERVE_MEDIA=True only for small deployments with no front web server.
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
SERVE_MEDIA = env.bool('SERVE_MEDIA', default=DEBUG)

# Credential uploads (IDs, licences, insurance) - private, never web-served; only the permission-checked view reads them.
PRIVATE_MEDIA_ROOT = Path(env('PRIVATE_MEDIA_ROOT', default='').strip() or BASE_DIR / 'private_uploads')  # blank in .env means default

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024


# Security hardening (only when DEBUG is off)

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
    SECURE_HSTS_PRELOAD = False
    if env.bool('BEHIND_PROXY', default=False):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# Email (used for future notifications; console in development)

EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Sajhya Health <no-reply@localhost>')


# Logging: everything to the console (the process manager / host collects it); errors also go to a rotating file.

LOG_DIR = Path(env('LOG_DIR', default='').strip() or BASE_DIR / 'logs')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'}},
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'},
    },
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', default='INFO')},
    'loggers': {'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False}},
}
if not DEBUG:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        LOGGING['handlers']['file'] = {
            'class': 'logging.handlers.RotatingFileHandler', 'filename': str(LOG_DIR / 'sajhya.log'),
            'maxBytes': 5 * 1024 * 1024, 'backupCount': 5, 'formatter': 'plain', 'level': 'WARNING'}
        LOGGING['root']['handlers'].append('file')
        LOGGING['loggers']['django.request']['handlers'].append('file')
    except OSError:
        pass  # read-only filesystem: console logging only


if TESTING:  # fast hashing and quiet logs keep the test run short and readable
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
    LOGGING['root']['level'] = 'CRITICAL'
    LOGGING['loggers']['django.request']['level'] = 'CRITICAL'
    LOGGING['loggers']['axes'] = {'handlers': [], 'level': 'CRITICAL', 'propagate': False}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
