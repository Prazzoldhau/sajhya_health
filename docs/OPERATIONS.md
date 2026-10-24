# Operations runbook

## 1. Environment variables

All configuration comes from the environment (a `.env` file beside `manage.py` in development). `.env.example` lists every
variable with comments. The important ones:

| Variable | Dev | Production | Notes |
| --- | --- | --- | --- |
| `DEBUG` | `True` | **`False`** | Default is False. With it off the app refuses to start without a real key/hosts/DB. |
| `SECRET_KEY` | any | 40+ random chars | Changing it signs everyone out and invalidates password-reset links. Keep it secret and stable. |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | your domains | |
| `CSRF_TRUSTED_ORIGINS` | - | `https://your.domain` | Needed behind an HTTPS proxy. |
| `DATABASE_URL` | MySQL or SQLite | `mysql://user:pass@host:3306/sajhya_health` | Use a dedicated MySQL user with rights on that one database only. URL-encode special characters in the password. |
| `BEHIND_PROXY` | - | `True` if nginx/Passenger/load balancer terminates TLS | Trusts `X-Forwarded-Proto` and `X-Forwarded-For`. Wrong value = redirect loops or everyone sharing one IP for lockouts. |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | - | `True`, `31536000` | HSTS: once enabled, browsers insist on HTTPS for a year. |
| `PRIVATE_MEDIA_ROOT` | blank (= `private_uploads/`) | folder **outside** the code | Credentials, patient pictures, lab reports. Back it up. |
| `SERVE_MEDIA` | `True` | `False` only if the web server serves `/media/` | Django serves `/media/` itself (profile and product photos). |
| `CACHE_DIR` | blank (= `cache/`) | writable folder | Counters for the password-reset throttle, shared by all workers. |
| `LOGIN_FAILURE_LIMIT` | 5 | 5 | Failed sign-ins before a 15-minute lockout. |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | console | SMTP | See TROUBLESHOOTING -> Email. |
| `LOG_LEVEL`, `LOG_DIR` | INFO | INFO | |
| `ADMIN_URL` | `admin/` | something unguessable, e.g. `office-7k2/` | Moves the Django admin off the default address that bots probe. |
| `FREE_PATIENT_LIMIT`, `PATIENT_SLOT_RATE` | 10, 200 | 10, 200 | Professional pricing: free patients, then NPR per extra patient. See PRICING.md. |
| `CLINIC_MONTHLY_PATIENT_CAP`, `CLINIC_OVERAGE_RATE` | 400, 200 | 400, 200 | Clinic pricing: new patients per month included, NPR per extra patient. |
| `THROTTLE_ENABLED` | automatic | `True` (default) | Per-IP limits on public forms (checkout 15/h, lab booking 15/h, sign-up 10/h). |

> **On cPanel hosting** follow [DEPLOY_CPANEL.md](DEPLOY_CPANEL.md) (plain git clone in the Terminal + `deploy/cpanel_deploy.sh`; not cPanel's Git screen). The generic steps below are for a server you control.

## 2. First deployment

```
git clone <repo> && cd sajhya-health
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env && nano .env                         # set the production values above
python manage.py migrate
python manage.py load_icd10 && python manage.py load_exercises && python manage.py load_pharmacy \
  && python manage.py load_lab_catalog && python manage.py load_catalog && python manage.py load_scales
python manage.py createsuperuser                          # the first staff user
python manage.py collectstatic --noinput
python manage.py check --deploy                           # only the HSTS-preload notice is acceptable
gunicorn sajhya_health.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

Put nginx/Apache in front (TLS, `/media/` alias if `SERVE_MEDIA=False`). Passenger hosts use `passenger_wsgi.py`.
Check `https://your.domain/healthz/` -> `{"status": "ok"}`. Create a test professional account and walk through
signup -> approval (as staff, at `/accounts/review/`) once before announcing.

## 3. Updating

```
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
# restart the app (gunicorn: systemctl restart ...; Passenger: touch tmp/restart.txt)
```

Rules of thumb: take a database backup **before** `migrate` when a release contains new migrations; never edit an applied
migration (add a new one); run `python manage.py test` before deploying.

## 4. Backups and restore

Back up **both** of these together - they refer to each other:

1. **The database**: `mysqldump --single-transaction -u user -p sajhya_health > sajhya_$(date +%F).sql`
2. **`PRIVATE_MEDIA_ROOT`** (credentials, patient pictures, lab reports) and **`media/`** (public photos).

`static/` images are part of the code/deploy, not user data. Clinic logos and banners are in `media/clinic_logos/` and `media/clinic_banners/` (covered by the `media/` backup). Restore = load the SQL into an empty database, copy the
folders back, run `migrate` (no-op if versions match). Test a restore on another machine at least once; a backup you
have never restored is a guess. Patient data is sensitive: encrypt backups and restrict who can read them.

## 5. Everyday tasks

| Task | How |
| --- | --- |
| Approve / reject a professional | Sign in as staff -> `/accounts/review/` (document links open for staff). |
| Reset a user's password | The user: "Forgot your password?". Staff, manually: `python manage.py changepassword USERNAME`. |
| Unlock a locked-out user | `python manage.py axes_reset_username USERNAME` (or `axes_reset` for everyone). |
| See failed sign-ins | `python manage.py axes_list_attempts` |
| Make someone staff | Admin -> Users -> tick "Staff status" (or `shell`). Superusers: `createsuperuser`. |
| Change plan prices / patient limit / features | Admin -> Billing -> Plans (also drives the package page and landing page). |
| Add or reprice pharmacy / lab / marketplace items | Admin -> Pharmacy products / Lab tests / Lab test panels / Products. |
| Process shop, pharmacy and lab orders | Admin -> Orders (filter by type) / Lab test requests; change the status as they progress. |
| Add exercises or images | Admin -> Exercises (image path like `/static/exercises/knee/lunge.png`, or step images). |
| Edit the ICD-10 list | Admin -> ICD-10 codes (`load_icd10` re-adds missing codes, never deletes). |
| Look at data | Admin, or `python manage.py shell`. |

## 6. Monitoring and logs

- **Uptime**: point a monitor at `/healthz/` (200 = app and database reachable, 503 = database unreachable).
- **Logs**: `logs/sajhya.log` (warnings+errors, rotating 5 x 5 MB) when `DEBUG=False`; everything also goes to the console
  of the process manager (`journalctl -u <service>` etc.). Sign-in lockouts are logged by `axes`; mail failures as
  `Failed to send password reset email`.
- **Disk**: watch the free space of `PRIVATE_MEDIA_ROOT` and the database - uploads are small (pictures are resized to
  640 px) but accumulate.
- **Sessions** are stored in the database (`django_session`); expired ones can be purged with `python manage.py clearsessions`
  (schedule it weekly).

## 7. Security checklist

- `DEBUG=False`, strong `SECRET_KEY`, `check --deploy` clean.
- HTTPS everywhere; `BEHIND_PROXY` correct; HSTS on.
- DB user limited to its own database; `.env` readable only by the app user; never commit `.env`.
- `PRIVATE_MEDIA_ROOT` outside the web root, not world-readable, backed up and ideally on an encrypted volume
  (files are **not** encrypted at rest by the application).
- Staff accounts: few, with strong unique passwords. The admin can see everything - set `ADMIN_URL` to an unguessable
  address and restrict it by network or VPN if you can.
- Patient data belongs to the professional who created it. The only cross-professional path is a **clinic** (its owner and
  accepted physios share the clinic's patients; contact details stay with the owner) - see CLINICS.md. Do not add other paths
  without an explicit consent model.
- Run `python manage.py test` (it includes the site-wide QA sweeps in `sajhya_health/test_qa.py`) before every deploy, and
  `python scripts/qa_mysql_crawl.py` / `scripts/qa_mysql_writes.py` against the production-like MySQL database (see QA_REPORT.md).
- Keep dependencies updated: `pip list --outdated`, then run the tests.

## 8. Scheduled jobs

**Recommended: once a month** (1st, early morning): `python manage.py clinic_usage` - refreshes every clinic's patient-enrolment
count for the month that just ended and this one, and prints what each clinic owes for going over its monthly cap, so the
dues are ready before billing. It is safe to run any time and optional (the clinic dashboard refreshes the numbers itself).
Staff then collect the money and mark months paid in the admin (Clinics -> Clinic monthly usage -> *Mark as paid*).

Nothing else needs a scheduler: statuses such as package "Expired", medicine "Completed" and appointment sync are
*derived when displayed*. Optional housekeeping: `clearsessions` weekly; database backups daily.

**Staff tasks that happen in the admin** (no scheduler involved): activating a Clinic plan request (Clinics -> Clinic subscriptions),
marking patient-slot orders paid (Billing -> Slot orders -> *Mark paid and add the slots*), marking clinic monthly dues paid, and
processing orders / lab bookings. Check these lists daily - customers are waiting on them.

## 9. The exercise library on a new server

`python manage.py load_exercises` loads **everything** the library has, from `exercises/fixtures/library.json` (built from the live site): 790
exercises, regions, 1,928 step-image rows, the main picture path, the **YouTube link** and the **hosted video link** of each exercise, and the Nepali
descriptions. It only loads a picture path if the file really exists under `static/exercises/` (the command reports how many it skipped), so make
sure the folder is deployed first (it is about 750 MB; consider rsync / an object store / Git LFS rather than a plain `git push`). Run it on a
**fresh** database; on a database that held an older library add `--prune` once to remove the old entries. Videos are not files here: the YouTube
and hosted (Supabase) links are stored as URLs and played from there.
