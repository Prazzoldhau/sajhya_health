from django.db import migrations

FOCUS = ['Sports Rehab', 'Pediatrics', 'Geriatrics', 'Orthopedics', 'Neurology', 'Vestibular Therapy']
SERVICES = ['In-clinic visits', 'Home healthcare', 'Telehealth / video consultations']


def seed(apps, schema_editor):
    for model_name, names in (('ClinicalFocus', FOCUS), ('ServiceType', SERVICES)):
        model = apps.get_model('accounts', model_name)
        for name in names:
            model.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [('accounts', '0003_professional_profile')]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
