"""Entry point for hosts that run Python apps through Phusion Passenger (e.g. cPanel "Setup Python App").

Point the app's startup file at this module; Passenger calls `application`.
cPanel overwrites this file with its own template (which uses `imp`, gone in Python 3.12) whenever the Python app is created or recreated:
the deploy script copies this version back every time (deploy/cpanel_deploy.sh), so deploy again after recreating the app.
For gunicorn use:  gunicorn sajhya_health.wsgi:application --bind 127.0.0.1:8000 --workers 3
"""
import os
import sys
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # Passenger does not always put the app folder on the path

from sajhya_health.wsgi import application as django_application  # noqa: E402


def application(environ, start_response):
    # This host passes PATH_INFO still percent-encoded, so pictures with spaces or brackets in their names ("9 (023).png", sent as 9%20%28023%29.png) are
    # not found by the static file server. Decode it for file requests only; a decoded path never contains '%' unless the file name does.
    path = environ.get('PATH_INFO', '')
    if '%' in path and path.startswith(('/static/', '/media/')):
        environ['PATH_INFO'] = unquote(path)
    return django_application(environ, start_response)
