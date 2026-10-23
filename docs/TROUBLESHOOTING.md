# Troubleshooting

Find the symptom, read the cause, run the fix. Commands assume you are in the project folder with the virtual
environment active (`venv\Scripts\activate` on Windows). On a server, use the same commands with that server's Python.

**First three checks for almost anything**

1. `GET /healthz/` -> `{"status": "ok"}`? If not, the app cannot reach the database (see "Database" below).
2. The log: `logs/sajhya.log` (warnings and errors, rotating) and the console output of the process.
3. `python manage.py check` and `python manage.py migrate --plan` - configuration errors and unapplied migrations show up here.

---

## The site will not start

| You see | Cause | Fix |
| --- | --- | --- |
| `ImproperlyConfigured: Set SECRET_KEY ... (40+ characters) when DEBUG is off` | Production mode (DEBUG off) with a missing or weak key | Put a long random key in `.env`: `python -c "import secrets; print(secrets.token_urlsafe(60))"` |
| `ImproperlyConfigured: Set ALLOWED_HOSTS` | Same, hosts missing | `ALLOWED_HOSTS=your.domain,www.your.domain` |
| `ImproperlyConfigured: Set DATABASE_URL` | Same, database missing | `DATABASE_URL=mysql://user:pass@host:3306/sajhya_health` |
| `DisallowedHost: Invalid HTTP_HOST header` | The domain you browse to is not in `ALLOWED_HOSTS` | Add it, restart. |
| `django.db.utils.OperationalError: (1045, Access denied ...)` | Wrong DB user/password in `DATABASE_URL`; special characters in the password must be URL-encoded (`@` -> `%40`) | Fix `.env`; test with `mysql -u user -p`. |
| `OperationalError: (2002/2003, Can't connect ...)` | MySQL not running or wrong host/port | Start MySQL; check `DATABASE_URL`. |
| `ModuleNotFoundError: pymysql` / `axes` / `PIL` | Dependencies not installed in this environment | `pip install -r requirements.txt` |
| `You have N unapplied migration(s)` | Code updated, database not | `python manage.py migrate` |
| Works locally, `DEBUG=True` forgotten on the server | `.env` copied from dev | Production must have `DEBUG=False`. |

## Database

- **MySQL strict mode errors** such as `Data too long for column` or `Incorrect decimal value`: the settings enable
  `STRICT_TRANS_TABLES`, which is intentional (bad data is rejected instead of silently truncated). Fix the data or form,
  do not remove strict mode.
- **`Access denied ... to database 'test_sajhya_health'` when running tests**: expected - the app's MySQL user cannot
  create databases. Tests therefore run on in-memory SQLite automatically (see `TESTING` in `settings.py`). To run them
  on MySQL deliberately, grant CREATE on `test_%` and set `TEST_DATABASE_URL`.
- **Connections dropping after idle time**: `DB_CONN_MAX_AGE` (default 60 s) keeps connections open; lower it or set to 0 if
  your host closes idle connections quickly.
- **Slow page**: count queries - in `python manage.py shell` use `CaptureQueriesContext` around `Client().get(url)`.
  Typical pages make 3-20 queries; if one makes hundreds, an `.all()` is being evaluated inside a template loop
  (add `select_related` / `prefetch_related` in the view).

## Signing in, accounts, passwords

| You see | Cause | Fix |
| --- | --- | --- |
| "Too many failed sign-in attempts" (HTTP 429) | 5 wrong passwords for the same username + IP; locked 15 minutes (django-axes) | Wait, or clear it: `python manage.py axes_reset` (all) / `axes_reset_username drp`. A successful password reset also clears it. |
| Locked out even though the password is right, and everyone shares one IP | Behind a reverse proxy without `BEHIND_PROXY=True`, so every visitor looks like the proxy's IP | Set `BEHIND_PROXY=True` (only if you control the proxy that sets `X-Forwarded-For`). |
| Forgot-password email never arrives | See "Email" below | |
| "This link no longer works" on a reset link | Links last **1 hour**, work **once**, and only the newest email's link is valid | Request a new one. |
| "Too many requests" on the forgot-password page (429) | More than 5 reset requests from one IP in an hour | Wait an hour; the throttle lives in the cache (`CACHE_DIR`). To clear it now: delete the files in `CACHE_DIR`. |
| Signup says "An account with this email address already exists" | Emails are unique (case-insensitive) so a reset email can only mean one account | Use "Forgot your password?" or a different email. |
| Staff cannot see review pages | Account is not `is_staff` | `python manage.py shell -c "from django.contrib.auth.models import User; u=User.objects.get(username='NAME'); u.is_staff=True; u.save()"` |
| A user has no way in (no email, forgot password) | | Set one manually: `python manage.py changepassword NAME`. |
| `AxesBackendRequestParameterRequired` in a script/test | Calling `authenticate()` / `client.login()` without a request while lockout is on | Use the login form (`client.post('/accounts/login/')`), or `force_login`. Tests turn lockout off automatically. |

## Email (password reset and future notifications)

- **Development**: emails are *printed in the console* of `runserver` (`EMAIL_BACKEND=...console...`). Copy the link from there.
- **Production**: set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`, `EMAIL_PORT`,
  `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`.
- A mail failure is **not shown to the visitor** (so the form cannot reveal which addresses exist). Look in the log for
  `Failed to send password reset email` - the traceback right under it says why (auth failed, connection refused, ...).
- Test your SMTP settings: `python manage.py shell -c "from django.core.mail import send_mail; send_mail('t','body','from@x.com',['you@x.com'])"`.
- Gmail needs an **app password**, not the normal password. Some hosts block outbound port 587/465.
- Reset links are built from the request's host - they will say `localhost` if you triggered the reset from `localhost`.

## Pictures, files and uploads

| You see | Cause | Fix |
| --- | --- | --- |
| Patient picture shows initials instead of the photo | No photo, or the file is missing from `private_uploads/` (restored DB without files) | Re-upload (patient page -> pencil on the avatar). Always back up `private_uploads/` *with* the database. |
| Patient/professional document returns 404 | The file is gone from `PRIVATE_MEDIA_ROOT`, or you opened it as a different user (owner and staff only) | Check the path in the admin; restore the folder from backup. |
| Upload says "does not look like a valid PDF" | The file's real content does not match its extension (renamed file), or it is corrupt | Re-export the document as a real PDF/JPEG/PNG. |
| Upload says "larger than 5 MB" / "8 MB" | Size limits (documents/reports 5 MB, patient pictures 8 MB before resizing) | Compress the file. |
| Profile photo (professional) does not show | `/media/` is not served | Set `SERVE_MEDIA=True` for small deployments, or alias `/media/` to the `media/` folder in nginx/Apache. |
| Uploaded files land in the project folder on the server and disappear on redeploy | `PRIVATE_MEDIA_ROOT` left at its default inside the project | Set `PRIVATE_MEDIA_ROOT` to a folder outside the code, with restricted permissions, and back it up. |
| Where did my uploaded files go? | `private_uploads/professional/<user id>/` (credentials), `private_uploads/patients/<professional id>/` (patient pictures), `private_uploads/lab_reports/<professional id>/` (lab reports). Names are random on purpose. | |

## Images and static files

- **Exercise or product images missing (404 in the browser console)**: run `python manage.py collectstatic --noinput` in
  production, and make sure the web server/WhiteNoise serves `staticfiles/`. Exercise images live in `static/exercises/`,
  product images in `static/categorized_product/`, pharmacy in `static/pharmacy/`.
- **Only some exercises show pictures**: by design - the imported catalogue only had images for ~160 exercises (step
  sequences) plus ~83 single images. The rest show a placeholder. Add more via the admin (Exercise -> image path or step images).
- **Page looks unstyled in production**: static files not collected, or `STATIC_URL`/proxy mismatch. Run `collectstatic`,
  hard-refresh (Ctrl+F5).
- **A page looks plain / unstyled (serif text, no layout, no icons)**: its CSS did not load. Bootstrap and Font Awesome are
  **bundled** in `static/vendor/` (no CDN), so the cause is the static files themselves: in production run
  `python manage.py collectstatic --noinput` and check the web server serves `/static/`; in development open
  `/static/accounts/auth.css` in the browser - a 404 means the dev server is not serving static (`DEBUG` off, or the wrong
  folder). Hard-refresh (Ctrl+F5) after fixing. Only the landing page, shop, pharmacy and lab pages still load Google Fonts
  (optional; they fall back to system fonts if blocked).
- **Icons show as empty squares**: `static/vendor/fontawesome/webfonts/fa-solid-900.woff2` is missing or blocked.
- **Logo missing**: `static/images/logo-64.png`, `logo-128.png`, `favicon.png` (generated from `icon.png`; see ARCHITECTURE).
- **Product images 404 only in production**: filenames contain spaces/brackets; they are URL-encoded by the code. If the
  files exist in `static/` and were collected, check the web server does not decode `%20`/`%28` twice.

## Catalogues are empty (exercises, pharmacy, lab, ICD-10, marketplace)

The reference data ships as fixtures and is loaded by commands. They are safe to re-run (they update, not duplicate):

```
python manage.py load_exercises      # 790 exercises, regions, step images, YouTube + hosted video links (add --prune once if an older library is loaded)
python manage.py load_pharmacy       # 35 pharmacy products
python manage.py load_lab_catalog    # 33 lab tests + 10 panels
python manage.py load_icd10          # ~12,000 WHO ICD-10 codes (diagnosis lookup)
python manage.py load_catalog        # 259 marketplace products + 16 categories
```

- Diagnosis lookup shows nothing -> `load_icd10` was never run (the code table is empty).
- "Medicine / lab test" dropdown shows nothing in a patient profile -> `load_pharmacy` / `load_lab_catalog`.
- Pharmacy prices all read "Price on request": the imported pharmacy items had price 0. Set prices in the admin (Pharmacy
  products) - this is data, not a bug.

## Appointments, calendar and time

- **Appointment appears at the wrong hour**: the site runs on **Asia/Kathmandu** (`TIME_ZONE`). Times are stored in UTC and
  shown in Nepal time. A wrong hour usually means the *server's* clock/time zone is wrong, or someone changed `TIME_ZONE`.
- **Calendar column missing an appointment**: cancelled appointments are hidden by design; a very early/late appointment
  extends the visible hours automatically.
- **Dashboard "Today's appointments" differs from the calendar**: both count scheduled (not cancelled/attended) appointments
  starting today in Nepal time.
- **A patient's "next appointment" is empty although one is booked**: it is recomputed whenever an appointment is booked,
  cancelled, attended or deleted (`sync_next_appointment`). If data was edited directly in the DB, open and save any
  appointment action for that patient, or run:
  `python manage.py shell -c "from accounts.models import Patient; from accounts.appointments import sync_next_appointment; [sync_next_appointment(p) for p in Patient.objects.all()]"`

## Billing and packages

- **A package did not use a session when a visit was recorded**: sessions are used only when the patient has a package with
  status *Active* that is not expired and not already completed, and the visit was recorded through the visit form or by
  marking an appointment attended (both call `accounts.services.record_visit`). Check the package card: Completed /
  Expired / Cancelled packages never count. Visits created directly in the admin do not use sessions.
- **Package shows "Expired" with sessions left**: the package length (1/2/3/4 weeks = 7/14/21/28 days) has passed.
  Start a new package; expired ones are not extended automatically.
- **A payment was capped**: recorded payments never exceed the balance due - paying 5,000 on a 2,000 balance records 2,000.
- **"Revenue Today" looks too low/high**: it is today's billing-book entries plus package payments recorded today (Nepal time).
- **"Your Professional plan allows up to 500 patient records"**: the plan limit (Admin -> Plans -> patient limit). Clear the
  field for unlimited.

## Patient profile, rehab and labs

- **Physiotherapy section says "No physiotherapy has been recorded yet"**: it is read from visits, treatment plans and
  exercise prescriptions; it has no entry form of its own. Record a visit / build a plan / prescribe exercises.
- **Occupational / speech / behavioural notes**: these *are* typed in (they have no daily-record source).
- **A medicine says "Completed" though marked active**: its end date has passed (derived automatically).
- **Lab report will not open**: private; opens only for the owning professional. 404 for anyone else.

## "I get a 404 / 403 / 500 page"

- **404 on a patient/plan/package/entry that exists**: you are signed in as a different professional. Records are
  visible only to their owner (a 404, not a 403, on purpose).
- **404 on `/accounts/patients/`** for a Client/Clinic/Enterprise account: those account types have no clinical workspace yet
  (they land on the welcome page).
- **Redirected to the welcome page / "Your credentials have not been verified yet"**: by design the whole workspace (dashboard,
  patients incl. Add patient, appointments, plans, billing, exercises, profile sections, searches) is closed until staff
  **approve** the professional (status "draft", "submitted" or "rejected" are all locked). A staff member approves at
  `/accounts/review/`; the user is then redirected to the dashboard on the next page load. Script/AJAX calls from a locked
  account get a JSON 403. Enforced in `accounts/middleware.py` (prefix list `WORKSPACE_PATH_PREFIXES` in settings) and in
  `accounts/access.py`. **If you add a new workspace URL area and it works for unapproved users, add its prefix to that list.**
- **A patient cannot see an earlier order in My orders**: it was placed as a guest. They can claim it with the order number and the email used (My orders -> *Placed one before you had an account?*).
- **Patient cannot link / sees nothing in the portal**: see [PORTAL.md](PORTAL.md) (codes expire after 7 days and work once; drafts are not shown).
- **SOAP note cannot be saved / edited**: see the troubleshooting list in [SOAP_NOTES.md](SOAP_NOTES.md) (drafts are author-only; final notes are locked).
- **`audit_live_dump` says UNMAPPED**: the live schema changed or a model field was renamed; see [LIVE_DATABASE.md](LIVE_DATABASE.md).
- **"You have used all your patient slots"** / a clinic owes money for extra patients: see [PRICING.md](PRICING.md) (staff mark slot orders / monthly dues paid in the admin).
- **Too many orders/bookings/accounts from this connection**: the per-IP limit on public forms (15 orders/hour, 15 lab bookings/hour, 10 sign-ups/hour); wait an hour or set `THROTTLE_ENABLED=False` while testing. Behind a proxy make sure `BEHIND_PROXY=True`, otherwise everyone shares one IP.
- **A professional says they paid for the Clinic plan but cannot create a clinic**: activate it in the admin (Clinics -> Clinic subscriptions -> action). See [CLINICS.md](CLINICS.md).
- **Assessment pages empty / "No forms yet"**: run `python manage.py load_scales`; see [ASSESSMENTS.md](ASSESSMENTS.md).
- **A user cannot change their name/licence in Settings**: by design (see DECISIONS). Staff edit it in the Django admin -> Professional profiles.
- **Report numbers look wrong**: check the definitions in `accounts/reports.py` (a patient only counts as *seen* if a Visit exists; package dues use the stored `amount_paid`). Diagnoses group by the ICD-10 code, so patients entered without a code are grouped by their free-text diagnosis.
- **A patient is missing from Recent patients**: the list is ordered by `Patient.last_activity` (added/opened/visit). Patients not touched for long fall off the top 4-5; use the search or *View all*.
- **Exercise shows a grey-green letter instead of a picture**: that library exercise has no image file here (about 770 of 790 have one). After a deploy make sure `static/exercises/` came across and run `collectstatic`.
  Add one in the admin (Exercises -> *Image path* or step images); it shows everywhere immediately.
- **403 CSRF failed**: the form was open too long, cookies are blocked, or the site is served on a domain not in
  `CSRF_TRUSTED_ORIGINS` (needed for HTTPS behind a proxy: `CSRF_TRUSTED_ORIGINS=https://your.domain`).
- **500**: read `logs/sajhya.log` - the traceback is there. The visitor only sees a generic page.
- **Infinite redirect loop after enabling HTTPS**: the proxy terminates TLS but Django does not know -> set `BEHIND_PROXY=True`
  (so `X-Forwarded-Proto` is trusted), or set `SECURE_SSL_REDIRECT=False` if the proxy already redirects.

## JavaScript / the browser

- **A button does nothing**: open the browser console (F12). Shared behaviour (modals, type-ahead search) is in
  `static/js/sajhya-ui.js`; if that file 404s (static not collected) every modal stops opening.
- **Every inline script is syntax-checked by a test** (`sajhya_health/test_javascript.py`, needs `pip install -r
  requirements-dev.txt`). If you edit a template script, run `python manage.py test sajhya_health.test_javascript`.
- **Patient search dropdown empty**: it needs at least one non-discharged patient; the endpoint is
  `/accounts/appointments/patients/?q=...` and must return JSON (a login redirect means the session expired).

## Tests

- `python manage.py test` should end with `OK`. To run one area: `python manage.py test billing`, `accounts.tests.test_plans`.
- A failing **`test_end_to_end`** means two features that work alone no longer work together - fix that first.
- Tests never touch your real data (they use a throwaway in-memory database) and redirect uploads to temporary folders.
- `ModuleNotFoundError: esprima` - the JavaScript test is skipped without it; install `requirements-dev.txt` to enable.

## Still stuck?

1. Reproduce it in a test (copy the closest test in `*/tests*.py`) - that also becomes the regression test.
2. `python manage.py shell` and reproduce with `django.test.Client` as the affected user (`client.force_login(user)`).
3. Read the relevant section of [ARCHITECTURE.md](ARCHITECTURE.md) and the decision notes in [DECISIONS.md](DECISIONS.md).
