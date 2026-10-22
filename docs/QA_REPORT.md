# Quality assurance report (pre-deployment)

Date: 2026-10-22. Scope: the whole web app (accounts, onboarding, patients, appointments, plans, SOAP notes, assessments, exercises,
billing, reports, clinics, patient portal, marketplace, pharmacy, lab) - 334 automated tests plus the sweeps below.

## What was done

| Check | How | Result |
| --- | --- | --- |
| Whole-site crash sweep | `sajhya_health/test_qa.py`: every URL route, GET and POST, as anonymous / client / unapproved professional / approved professional / staff (~2,500 requests) | no 500s |
| Access control | anonymous visitors may open only an explicit list of public pages; workspace pages are closed to clients and unapproved professionals | pass (list must be updated on purpose when a public page is added) |
| GET never changes data | snapshot every table, GET every route as three roles, compare | pass (only idempotent blank default rows are created lazily) |
| Broken links | follow every internal link on the main workspace, public and dashboard pages | none broken |
| Hostile input (XSS) | HTML/JS in names, notes, clinic text, orders, search boxes; pages must show it escaped | pass |
| Odd data | Nepali script, emoji, very long text, 29 Feb, 1900 and future dates, empty database, bad report periods | one bug fixed (below) |
| Query budgets (N+1) | `assertNumQueries`-style ceilings per page and "patients page does not grow with data" | pass |
| MySQL reality check | `scripts/qa_mysql_crawl.py`: 1,545 GETs on the real MySQL DB; `scripts/qa_mysql_writes.py`: all write paths with unicode/JSON on MySQL in a rolled-back transaction | pass; DB is utf8mb4 so Nepali + emoji store correctly |
| Deploy settings | `check --deploy` with production-like env; wsgi import; `makemigrations --check` | clean (only the optional HSTS-preload hint) |
| Static analysis | pyflakes over all apps | unused imports/variables removed; clean |
| Visual check | `scripts/qa_screenshots.py` (headless Edge, desktop + phone width) over the main pages | one contrast bug fixed (below) |
| JavaScript | esprima parses every inline script and `static/js/*.js` on each test run | pass |

## Bugs found and fixed during QA

1. **A patient could be saved with a date of birth in the future** (or over 120 years ago). Now refused with a message.
2. **Unreadable button text** in the new "slots used" and "clinic invitation" bars (dark text on green) - caused by a CSS class
   collision; fixed.
3. **`exercise.is_expired` used the server's date** instead of Nepal's date; now uses the local date.
4. **Public forms had no rate limit** - anyone could spam orders, lab bookings or accounts. Added per-IP limits (checkout 15/h,
   lab 15/h, sign-up 10/h) - `sajhya_health/throttle.py`.
5. **Django admin at the default address** - now configurable with `ADMIN_URL`.
6. Dead imports/variables removed (no behaviour change).

## Known risks and recommendations before and after go-live

**Do before go-live**
- Set the production `.env` (see OPERATIONS.md), including `ADMIN_URL`, real SMTP, `PRIVATE_MEDIA_ROOT` outside the web root.
- Do one **manual smoke test** on the real server with a real browser and phone (sign up as professional -> staff approve -> add
  patient -> SOAP note -> plan -> publish -> link a patient account -> order + lab booking). No automated browser (Selenium/
  Playwright) tests exist; the automated suite renders pages and checks HTML/JS syntax but does not click.
- **Send a real password-reset email** through the SMTP provider (tests use the console backend).
- Test a **backup restore** once (database + `PRIVATE_MEDIA_ROOT` + `media/`).
- Run `pip install pip-audit && pip-audit` on the server (dependency vulnerability scan needs internet; not run here).
- Decide the staff routine for the admin queues (clinic plan requests, patient-slot orders, clinic monthly dues, orders, lab bookings).

**Accepted limitations (documented)**
- Payments are manual (no eSewa/Khalti); throughput depends on staff.
- No SMS/email notifications (reminders, portal codes are handed over by the physio).
- Public forms are rate-limited but have no CAPTCHA; add one if abuse appears.
- Files are not encrypted at rest by the application (use an encrypted volume).
- No load test was run. Query budgets are in place; a 3-worker gunicorn on a modest server should handle a clinic-sized load,
  but measure before onboarding hundreds of concurrent users.
- Accessibility (screen readers, keyboard-only) has not been formally audited beyond fixing contrast bugs found by eye.
- Image weight: `static/exercises` and product images are about 330 MB in the repository (consider Git LFS / CDN).
- Tests run on SQLite for speed; MySQL-only behaviour is covered by the two `scripts/qa_mysql_*.py` scripts - **re-run them after any
  model/query change** on a copy of the production database.

## How to repeat the QA

```
python manage.py test                       # everything, including sajhya_health/test_qa.py (about 35 s)
python manage.py check --deploy             # with the production .env loaded
python scripts/qa_mysql_crawl.py            # GET sweep on the real database (MySQL)
python scripts/qa_mysql_writes.py           # write paths on MySQL, rolled back
python scripts/qa_screenshots.py            # screenshots to look at
```
