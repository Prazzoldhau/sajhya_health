"""Entry point for hosts that run Python apps through Phusion Passenger (e.g. cPanel "Setup Python App").

Point the app's startup file at this module; Passenger calls `application`.
For gunicorn use:  gunicorn sajhya_health.wsgi:application --bind 127.0.0.1:8000 --workers 3
"""
from sajhya_health.wsgi import application  # noqa: F401
