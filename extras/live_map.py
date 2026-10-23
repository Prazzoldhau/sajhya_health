"""Where every table and column of the live sajhya.com database lives in this project.

`python manage.py audit_live_dump <dump.sql | extras/live_schema.json>` checks this map against a dump: any live column without a home is
reported, so the project cannot silently drift away from the live data model. The loader (when written) uses the same map.

Entries: live table -> {'model': 'app.Model', 'cols': {live_column: 'field' | 'app.Model.field' | None}, 'why': {live_column: reason}}.
  - a column not listed in `cols` is expected to exist under the same name on `model` (a foreign key `x_id` maps to the field `x`);
  - `'field'` renames it on the same model; `'app.Model.field'` sends it to another model (the live table was split);
  - `None` (with a reason in `why`) means deliberately not carried over.
Tables whose models live in the `extras` app are discovered automatically from the "(live table `...`)" note in their docstring.
"""
import re

from django.apps import apps

INTERNAL = {  # Django's own bookkeeping: rebuilt by Django, never carried over
    'auth_group': 'Django permissions are re-created by migrate', 'auth_group_permissions': 'same', 'auth_permission': 'same',
    'django_admin_log': 'admin history of the old site (3,600 rows) is not carried over', 'django_content_type': 'rebuilt by migrate',
    'django_migrations': 'the old site\'s migration history', 'django_session': 'login sessions (50,000 rows) expire; users sign in again',
    'account_app_user_groups': 'no groups were used (0 rows)', 'account_app_user_user_permissions': 'no per-user permissions were used (0 rows)',
}

EXISTING = {
    'account_app_user': {'model': 'auth.User', 'cols': {
        'phone': 'accounts.ProfessionalProfile.mobile', 'user_type': 'accounts.Account.account_type', 'personal_code': 'accounts.Account.personal_code',
        'created_at': 'accounts.Account.created_at', 'license_number': 'accounts.ProfessionalProfile.license_number',
        'pairing_token': 'accounts.Account.pairing_token', 'license_verified': 'accounts.ProfessionalProfile.status'}},
    'assessment_app_patientscaleassessment': {'model': 'assessments.AssessmentResult', 'cols': {
        'created_at': 'assessments.AssessmentSession.created_at', 'scale': 'scale_code', 'items': 'answers', 'total_score': 'score',
        'created_by_id': 'assessments.AssessmentSession.assessor', 'patient_id': 'assessments.AssessmentSession.patient'}},
    'billing_app_billingentry': {'model': 'billing.BillingEntry', 'cols': {'physio_id': 'professional'}},
    'billing_app_packagepayment': {'model': 'billing.PackagePayment', 'cols': {}},
    'billing_app_patientpackage': {'model': 'billing.PatientPackage', 'cols': {'physio_id': 'professional'}},
    'clinic_account_clinic': {'model': 'clinics.Clinic', 'cols': {'clinic_name': 'name', 'clinic_code': 'code', 'created_by_id': 'owner', 'updated_at': None}, 'why': {'updated_at': 'not kept'}},
    'clinic_account_clinicphysio': {'model': 'clinics.ClinicMember', 'cols': {'is_active': 'status'}},
    'clinic_account_queueentry': {'model': 'clinics.QueueEntry', 'cols': {}},
    'exercise_app_exercisemain': {'model': 'exercises.ExerciseMain', 'cols': {}},
    'exercise_app_exercisestepimage': {'model': 'exercises.ExerciseStepImage', 'cols': {}},
    'exercise_app_region': {'model': 'exercises.Region', 'cols': {}},
    'exercise_app_subregion': {'model': 'exercises.SubRegion', 'cols': {}},
    'exercise_feedback': {'model': 'exercises.ExerciseFeedback', 'cols': {}},
    'prescriptions': {'model': 'exercises.Prescription', 'cols': {'created_by_id': 'professional'}},
    'prescription_exercises': {'model': 'exercises.PrescriptionExercise', 'cols': {'exercise_id_in_library': 'library_exercise_id'}},
    'lab_app_labtest': {'model': 'lab.LabTest', 'cols': {}},
    'lab_app_labtestpanel': {'model': 'lab.LabTestPanel', 'cols': {}},
    'lab_app_labtestpanel_tests': {'model': 'lab.LabTestPanel.tests', 'm2m': True, 'cols': {}},
    'lab_app_labtestrequest': {'model': 'lab.LabTestRequest', 'cols': {}},
    'lab_app_labtestrequestitem': {'model': 'lab.LabTestRequestItem', 'cols': {}},
    'marketplace_app_category': {'model': 'marketplace.Category', 'cols': {}},
    'marketplace_app_product': {'model': 'marketplace.Product', 'cols': {}},
    'marketplace_app_productvariant': {'model': 'marketplace.ProductVariant', 'cols': {}},
    'marketplace_app_productimage': {'model': 'marketplace.ProductImage', 'cols': {}},
    'marketplace_app_pharmacyproduct': {'model': 'marketplace.PharmacyProduct', 'cols': {}},
    'marketplace_app_order': {'model': 'marketplace.Order', 'cols': {}},
    'marketplace_app_orderitem': {'model': 'marketplace.OrderItem', 'cols': {}},
    'personal_account_addpatient': {'model': 'accounts.Patient', 'cols': {
        'patient_name': 'name', 'patient_contact': 'phone', 'patient_diagnosis': 'diagnosis', 'created_by_id': 'professional', 'origin_clinic_id': 'clinic',
        'origin_enterprise_id': 'enterprise', 'password': 'legacy_password_hash', 'username': 'legacy_username',
        'completed_session': None, 'is_deleted': None, 'deleted_at': None, 'diagnosis_code_id': None},
        'why': {'completed_session': 'derived: counted from recorded visits', 'is_deleted': 'soft-deleted patients are not carried over',
                'deleted_at': 'same', 'diagnosis_code_id': 'the live code table was empty; the ICD-10 text is kept in icd10_code'}},
    'personal_account_diagnosiscode': {'model': 'accounts.Icd10Code', 'cols': {'label': 'title', 'chapter': None, 'is_active': None},
                                       'why': {'chapter': 'this project loads the full WHO ICD-10 list instead (live table had 0 rows)', 'is_active': 'same'}},
    'personal_account_patientaid': {'model': 'profiles.AidEntry', 'cols': {}},
    'personal_account_patientbloodtest': {'model': 'profiles.LabEntry', 'cols': {}},
    'personal_account_patientmedicalprofile': {'model': 'profiles.PatientProfile', 'cols': {
        'nursing_mobility_assistance': 'mobility_assistance', 'nursing_wound_catheter_care': 'wound_catheter_care', 'last_updated_by_id': 'updated_by'}},
    'personal_account_patientmedication': {'model': 'profiles.MedicineEntry', 'cols': {'time_of_day': 'morning'}},
}

M2M_EXTRAS = {
    'donate_app_donationpledge_items': 'extras.DonationPledge.items',
    'find_physio_app_physioprofile_specializations': 'extras.PhysioListing.specializations',
    'marketplace_app_diagnosisproductmap_products': 'extras.DiagnosisProductMap.products',
}


def extras_tables():
    """live table -> 'extras.Model', read from each extras model's docstring."""
    found = {}
    for model in apps.get_app_config('extras').get_models():
        m = re.search(r'\(live table `(\w+)`\)', model.__doc__ or '')
        if m:
            found[m.group(1)] = f'extras.{model.__name__}'
    return found


def resolve(spec, default_model):
    """('app.Model', 'field') for a column spec, or None."""
    if spec is None:
        return None
    parts = spec.split('.')
    if len(parts) == 3:
        return f'{parts[0]}.{parts[1]}', parts[2]
    return default_model, spec


def has_field(model_label, name):
    app_label, model_name = model_label.split('.')
    model = apps.get_model(app_label, model_name)
    names = {f.name for f in model._meta.get_fields()} | {getattr(f, 'attname', f.name) for f in model._meta.get_fields()}
    return name in names or (name.endswith('_id') and name[:-3] in names)


def build_map():
    table_map = dict(EXISTING)
    for table, label in extras_tables().items():
        table_map[table] = {'model': label, 'cols': {}}
    for table, label in M2M_EXTRAS.items():
        table_map[table] = {'model': label, 'm2m': True, 'cols': {}}
    return table_map


def audit(schema):
    """schema: {table: [column names]}. Returns a report dict: unmapped tables / columns, missing targets, and counts."""
    table_map = build_map()
    report = {'tables': len(schema), 'internal': 0, 'mapped_tables': 0, 'columns': 0, 'unmapped_tables': [], 'unmapped_columns': [], 'missing_models': [], 'dropped': []}
    for table, columns in sorted(schema.items()):
        if table in INTERNAL:
            report['internal'] += 1
            continue
        entry = table_map.get(table)
        if entry is None:
            report['unmapped_tables'].append(table)
            continue
        report['mapped_tables'] += 1
        model_label = entry['model']
        if entry.get('m2m'):
            app_label, model_name, field = model_label.split('.')
            model = apps.get_model(app_label, model_name)
            if field not in {f.name for f in model._meta.get_fields()}:
                report['missing_models'].append(f'{table} -> {model_label}')
            report['columns'] += len(columns)
            continue
        try:
            app_label, model_name = model_label.split('.')
            apps.get_model(app_label, model_name)
        except LookupError:
            report['missing_models'].append(f'{table} -> {model_label}')
            continue
        for column in columns:
            report['columns'] += 1
            if column == 'id':
                continue
            spec = entry['cols'].get(column, column)
            target = resolve(spec, model_label)
            if target is None:
                report['dropped'].append((table, column, entry.get('why', {}).get(column, 'not carried over')))
            elif not has_field(*target):
                report['unmapped_columns'].append(f'{table}.{column} -> {target[0]}.{target[1]} (no such field)')
    return report


def parse_sql_schema(path):
    """{table: [columns]} read from the CREATE TABLE statements of a mysqldump / phpMyAdmin export (data rows are ignored)."""
    schema, current = {}, None
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            m = re.match(r'CREATE TABLE `(\w+)`', line)
            if m:
                current = m.group(1)
                schema[current] = []
                continue
            if current:
                col = re.match(r'\s+`(\w+)` \S', line)
                if col:
                    schema[current].append(col.group(1))
                if line.startswith(')'):
                    current = None
    return schema
