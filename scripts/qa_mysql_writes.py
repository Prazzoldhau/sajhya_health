"""Exercise the write paths (patient, SOAP note, plan, assessment, portal link, clinic, slot order, lab booking) on the REAL database
inside one transaction that is ROLLED BACK. Usage: python scripts/qa_mysql_writes.py"""
import json, os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'sajhya_health.settings'
sys.path.insert(0, '.')
django.setup()
from django.db import transaction, connection
from django.test import Client
from django.test.utils import setup_test_environment
setup_test_environment()
from django.contrib.auth.models import User
from django.urls import reverse
from accounts.models import Patient
from assessments.models import AssessmentScale

print('DB:', connection.vendor, connection.settings_dict['NAME'])
with connection.cursor() as cur:
    cur.execute("SELECT @@character_set_database, @@collation_database, @@sql_mode")
    print('charset/collation/sql_mode:', cur.fetchone())
problems = []

def check(label, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + label, detail if not ok else '')
    if not ok:
        problems.append(label)

with transaction.atomic():
    pro = User.objects.filter(account__profile__status='approved', is_active=True).first()
    c = Client(HTTP_HOST='127.0.0.1', raise_request_exception=False)
    c.force_login(pro)
    # 1. unicode + emoji patient (utf8mb4)
    name = 'QA सीता गुरुङ 🌿'
    r = c.post(reverse('accounts:patient-add'), {'name': name, 'date_of_birth': '1990-02-28', 'gender': 'F', 'phone': '9841999001', 'diagnosis': 'पिठ्यूँको दुखाइ 🙂'})
    patient = Patient.objects.filter(name=name).first()
    check('add patient with Nepali script + emoji', patient is not None and r.status_code in (302, 200), f'status {r.status_code}')
    if patient is None:
        # may be blocked by the slot limit on the dev account: lift it inside the rollback
        from billing.models import PatientAllowance
        a = PatientAllowance.for_profile(pro.account.profile); a.paid_slots += 50; a.save()
        r = c.post(reverse('accounts:patient-add'), {'name': name, 'date_of_birth': '1990-02-28', 'gender': 'F', 'phone': '9841999001'})
        patient = Patient.objects.filter(name=name).first()
        check('add patient (after lifting the slot limit)', patient is not None, f'status {r.status_code}')
    pid = patient.pk
    check('search finds the Nepali name', name in c.get('/accounts/patients/', {'q': 'सीता'}).content.decode())
    # 2. SOAP note with JSON columns
    note_post = {'note_date': '2026-10-01', 'note_type': 'initial', 'chief_complaint': 'दुखाइ 🌿', 'action': 'final', 'pain_now': '5',
                 'rom_json': json.dumps([{'movement': 'Knee flexion', 'side': 'Right', 'active': '90', 'passive': '110', 'pain': True, 'note': 'ठीक'}]),
                 'measures_json': json.dumps([{'name': 'Knee ROM', 'unit': '°', 'baseline': '90', 'target': '130'}]),
                 'goals_json': json.dumps([{'text': 'Walk', 'term': 'short', 'target_date': '2026-12-01'}]), 'red_flags': ['night_pain'], 'impression': 'ACL'}
    r = c.post(reverse('soapnotes:new', args=[pid]), note_post)
    from soapnotes.models import SoapNote
    note = SoapNote.objects.filter(patient_id=pid).first()
    check('save a SOAP note (JSON columns)', note is not None and note.rom and note.measures[0]['target'] == '130', f'status {r.status_code}')
    check('SOAP note detail renders', c.get(reverse('soapnotes:detail', args=[note.pk])).status_code == 200 if note else False)
    # 3. treatment plan pre-filled from the note, saved
    page = c.get(reverse('accounts:plan-new', args=[pid]))
    state = page.context['state'] if page.context else None
    check('plan builder pre-fills from the SOAP note', bool(state and state['measures']))
    if state:
        state['phases'][0]['items'] = [{'kind': 'hep', 'text': 'Heel slides', 'dosage': '3x10'}]
        r = c.post(reverse('accounts:plan-create', args=[pid]), json.dumps({**state, 'action': 'publish'}), content_type='application/json')
        check('save + publish a plan', r.status_code == 200, r.content[:200])
    # 4. assessment
    scale = AssessmentScale.objects.filter(code='tug').first()
    if scale:
        item = scale.items.first()
        r = c.post(reverse('assessments:fill', args=[pid]), {'scales': str(scale.pk), 'assessed_on': '2026-10-01', f'i_{item.pk}': '12'})
        check('record an assessment', r.status_code == 302, f'status {r.status_code}')
    else:
        print('skip assessment (scales not loaded in this DB)')
    # 5. portal invite + link by a client user
    r = c.post(reverse('portal:invite', args=[pid]))
    code = r.context['code'] if r.status_code == 200 else None
    check('create a portal code', bool(code), f'status {r.status_code}')
    cl = User.objects.filter(account__account_type='client').first()
    if code and cl:
        cc = Client(HTTP_HOST='127.0.0.1', raise_request_exception=False); cc.force_login(cl)
        from portal.models import PatientLink
        PatientLink.objects.filter(user=cl).delete()  # inside the rollback only
        cc.post(reverse('portal:link'), {'code': code, 'dob': '1990-02-28'})
        check('patient links the record', PatientLink.objects.filter(user=cl, patient_id=pid).exists())
        for name_ in ('home', 'plan', 'exercises', 'advice', 'orders', 'lab'):
            check(f'portal {name_} renders', cc.get(reverse('portal:' + name_) + f'?p={pid}').status_code == 200)
    # 6. clinic with JSON hours + monthly usage
    r = c.post(reverse('clinics:create'), {'name': 'QA Clinic 🌿', 'phone': '015550001', 'province': 'Bagmati', 'district': 'Lalitpur', 'slot_minutes': '30',
                                           'open_sunday': 'on', 'start_sunday': '09:00', 'end_sunday': '17:00', 'amenities': ['parking'], 'specializations': ['sports']})
    from clinics.models import Clinic
    clinic = Clinic.objects.filter(name='QA Clinic 🌿').first()
    check('register a clinic (JSON hours, unicode)', clinic is not None, f'status {r.status_code}')
    if clinic:
        check('clinic dashboard + usage renders', c.get(reverse('clinics:detail', args=[clinic.pk])).status_code == 200)
    # 7. slot order
    r = c.post(reverse('accounts:settings'), {'tab': 'plan', 'quantity': '3'})
    from billing.models import SlotOrder
    check('order patient slots', SlotOrder.objects.filter(professional=pro.account.profile, quantity=3).exists())
    # 8. lab booking + marketplace order as guest, then claim
    from lab.models import LabTest, LabTestRequest
    test = LabTest.objects.filter(is_active=True).first()
    g = Client(HTTP_HOST='127.0.0.1', raise_request_exception=False)
    if test:
        r = g.post(reverse('lab:tests'), {'items': [f'test-{test.pk}'], 'customer_name': 'QA बुकिङ 🌿', 'customer_email': 'qa@example.com', 'customer_phone': '9800000000', 'delivery_address': 'काठमाडौं'})
        check('guest lab booking (unicode)', LabTestRequest.objects.filter(customer_email='qa@example.com').exists(), f'status {r.status_code}')
    # reports on real data
    for params in ({'period': 'month'}, {'period': 'week'}, {'period': 'custom', 'start': '2026-01-01', 'end': '2026-12-31'}, {'export': 'csv'}):
        check(f'report {params}', c.get('/accounts/reports/', params).status_code == 200)
    transaction.set_rollback(True)

print('\nPROBLEMS:' if problems else '\nALL WRITE PATHS OK on MySQL (rolled back)')
for p in problems:
    print(' -', p)
