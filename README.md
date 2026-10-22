# Sajhya Health

A Django platform for healthcare professionals and their patients.

> **Documentation lives in [`docs/`](docs/README.md)** - troubleshooting guide, operations runbook, architecture and the
> record of design decisions. If something is broken, open [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) first.

| Area | What it does |
| --- | --- |
| **Landing + packages** | Public landing page; **Get Started** leads to the Client / Professional / Clinic / Enterprise plans (prices and features come from the database) |
| **Accounts** | Signup and login for every account type, hashed passwords, login lockout after repeated failures, **forgot password** by email, change password |
| **Professional onboarding** | 4-step, save-and-resume signup (account, licence, private document uploads, practice) with a staff review queue (approve / reject with a reason) |
| **Dashboard** | Live numbers from patients, appointments, visits and billing |
| **Patients** | Search, filters, enrolment form with **private profile pictures**, ICD-10 diagnosis lookup (12,000+ WHO codes), visit history, notes |
| **Patient profile** | Allergies/history, **medicine** (from the pharmacy catalogue), **nursing** (vitals, care), **surgical aids**, **rehab** (physiotherapy pulled from the daily records; occupational, speech and behavioural therapy notes), **lab tests** (from the lab catalogue, with results and reports) |
| **Patient dashboard** | Every free Client account gets a web-app dashboard with a vertical menu: browse the **pharmacy, marketplace and lab investigations**; in **Settings** link a treatment record (one-time code from the physio + date of birth) to see the published plan, exercises (tick done, send feedback) and do's & don'ts ([docs/PORTAL.md](docs/PORTAL.md)) |
| **SOAP notes** | Patient **SOAP Notes** tab (right after Overview): a full physiotherapy S/O/A/P form with pain, red flags, ROM and strength tables, special tests, ICD-10, baseline metrics and goals; draft -> finalise (locked) with addenda; a new treatment plan starts from the latest note ([docs/SOAP_NOTES.md](docs/SOAP_NOTES.md)) |
| **Assessments** | Patient **Assessments** tab: choose a ready-made form or individual scales (25 shipped: Barthel, FIM, Berg, TUG, NIHSS, GCS, Ashworth, SARA, ODI, NDI, LEFS, GMFCS, 6MWT ...), record scores with automatic totals and interpretation, and track progress over time. Scales are data - add or change them in the admin ([docs/ASSESSMENTS.md](docs/ASSESSMENTS.md)) |
| **Clinic Connect** | A verified professional upgrades to the Clinic plan (staff activate it in the admin), creates clinics, invites **verified physios** (who must accept) and adds staff, registers patients under a clinic and runs a daily on-site queue; clinic overview shows counts only ([docs/CLINICS.md](docs/CLINICS.md)) |
| **Appointments** | Multi-day calendar with overlap handling, booking by patient search, unavailable blocks, to-do list |
| **Treatment plans** | Baseline measures, goals, phased interventions, progress readings, printable |
| **Reports** | Weekly, monthly or custom-range reports: KPIs, day-by-day activity, **new vs follow-up clients by age and sex** (HMIS-style aggregates), top ICD-10 diagnoses, appointments, money by payment mode, packages and dues, exercise adherence, referral sources; **CSV download** and print |
| **Settings** | Edit your mobile, photo, experience, focus areas and services; practice name/address/phone, facility (HMIS) code and default appointment length; email and password. Name, title and licence stay locked (verified by staff) |
| **Exercise library** | 788 exercises by region, with images; prescribe to patients and track completion; also feeds the plan builder |
| **Billing** | Daily billing book, plus **patient packages**: sell a patient a 1, 2, 3 or 4 week package with a set number of sessions and a price, take instalment payments; every completed session uses up a package session |
| **Marketplace, Pharmacy, Lab tests** | Public shop and pharmacy with carts and checkout; public lab-test booking; orders and bookings are managed in the Django admin |

## Local development

```
python -m venv venv
venv\Scripts\activate            # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt  # developers also: pip install -r requirements-dev.txt
copy .env.example .env           # then edit it (DEBUG=True for development)
python manage.py migrate
python manage.py load_icd10 && python manage.py load_exercises && python manage.py load_pharmacy \
  && python manage.py load_lab_catalog && python manage.py load_catalog && python manage.py load_scales    # reference data (safe to re-run)
python manage.py createsuperuser # staff account: reviews professional applications, manages orders
python manage.py runserver
```

In development, emails (for example the password-reset link) are **printed in the `runserver` console**.

Tests (334 of them; they run on in-memory SQLite, so no MySQL privileges are needed):

```
python manage.py test
```

`sajhya_health/test_end_to_end.py` follows a professional through the whole product; if it fails, start there.

## Production

The full runbook is [`docs/OPERATIONS.md`](docs/OPERATIONS.md). In short:

1. Set the variables from `.env.example`. With `DEBUG=False` the app refuses to start without a real `SECRET_KEY`
   (40+ chars), `ALLOWED_HOSTS` and `DATABASE_URL`; also set `CSRF_TRUSTED_ORIGINS`, `BEHIND_PROXY`, SMTP (`EMAIL_*`) and
   `PRIVATE_MEDIA_ROOT`.
2. `pip install -r requirements.txt`, `python manage.py migrate`, the `load_*` commands above, `createsuperuser`,
   `collectstatic --noinput`, `check --deploy`.
3. Run `gunicorn sajhya_health.wsgi:application --bind 127.0.0.1:8000 --workers 3` behind nginx/Apache (or Passenger via
   `passenger_wsgi.py`). Monitor `GET /healthz/`.
4. **Back up the database and `PRIVATE_MEDIA_ROOT` together** (credentials, patient pictures, lab reports).

Notes:

- **Static image weight**: `static/exercises/` (~290 MB) and `static/categorized_product/` hold the exercise and product
  images; consider Git LFS or an object store/CDN rather than keeping them in the repository.
- **Pricing**: Professional = first 10 patients free then NPR 200 each (patient slots); Clinic = 400 new patients a month included, NPR 200 for each extra, added as a due. See [`docs/PRICING.md`](docs/PRICING.md). Run `python manage.py clinic_usage` monthly.
- **Before deploying**: read [`docs/QA_REPORT.md`](docs/QA_REPORT.md) (checklist) and run the test suite.
- **Login lockout**: 5 failed attempts for the same username and IP lock sign-in for 15 minutes
  (`python manage.py axes_reset` clears it).
- **Time zone** is `Asia/Kathmandu`.
- **Account plans** (Client / Professional / Clinic / Enterprise) are editable in the admin under *Plans*. The Professional plan
  caps patient records at 500; Clinic and Enterprise are seeded as custom-priced.
- **Not built yet**: patient-facing logins, SMS reminders, online payments (eSewa/Khalti), and workspaces for Client, Clinic and
  Enterprise accounts (they land on a welcome page). See [`docs/DECISIONS.md`](docs/DECISIONS.md) for the full list.
