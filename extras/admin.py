from django.apps import apps
from django.contrib import admin

# These tables hold live-site data that has no screens here yet; the admin lets staff look at and fix it.
for model in apps.get_app_config('extras').get_models():
    admin.site.register(model)
