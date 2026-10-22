from django.db import migrations

SEED = {
    'Profession': ['physiotherapist', 'occupational therapist', 'doctors', 'pharmacist', 'nurse', 'dentist'],
    'ClinicType': ['dental', 'physiotherapy', 'speech therapy', 'rehab center', 'dermatology clinic'],
    'EnterpriseType': ['hospital', 'polyclinic', 'multispeciality clinic', 'ayurvedic clinic'],
}


def seed(apps, schema_editor):
    for model_name, names in SEED.items():
        model = apps.get_model('accounts', model_name)
        for name in names:
            model.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [('accounts', '0001_initial')]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
