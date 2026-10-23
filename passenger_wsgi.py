"""Entry point for hosts that run Python apps through Phusion Passenger (e.g. cPanel "Setup Python App").

Point the app's startup file at this module; Passenger calls `application`.
cPanel overwrites this file with its own template (which uses `imp`, gone in Python 3.12) whenever the Python app is created or recreated:
the deploy script copies this version back every time (deploy/cpanel_deploy.sh), so deploy again after recreating the app.
For gunicorn use:  gunicorn sajhya_health.wsgi:application --bind 127.0.0.1:8000 --workers 3
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # Passenger does not always put the app folder on the path

from sajhya_health.wsgi import application  # noqa: E402,F401
