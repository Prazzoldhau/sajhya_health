from django.contrib.admin.apps import AdminConfig


class SajhyaAdminConfig(AdminConfig):
    """The Django admin, with the clinics' patient records taken out of it (see sajhya_health/privacy.py)."""

    def ready(self):
        super().ready()  # finds every app's admin.py and registers its models
        from . import privacy
        privacy.hide_patient_data()
