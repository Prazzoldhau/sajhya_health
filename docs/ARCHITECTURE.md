# Architecture

## Apps and what they own

| App | Owns | Key files |
| --- | --- | --- |
| `accounts` | Users and account types, professional onboarding + staff review, patients (with private pictures), visits, appointments and to-dos, treatment plans, ICD-10 lookup, password reset, the workspace layout | `models.py`, `access.py`, `views.py`, `appointments.py`, `plans.py`, `auth_views.py`, `services.py`, `forms.py`, `images.py`, `templatetags/accounts_ui.py`, `templates/accounts/pro_base.html` |
| `reports` (inside `accounts`) | Weekly/monthly/custom reports as plain data (KPIs + table sections) that feed both the page and the CSV | `reports.py` (all queries and definitions), `report_views.py`, `templates/accounts/reports.html` |
| `billing` | Daily billing book (bills can be paid in full, part paid or left **on credit**; later payments are `EntryPayment` rows, and "money taken" counts payments by the day they were received), **patient packages** (1-4 weeks, sessions, payments), **account plans** (the package page content) | `models.py`, `views.py` |
| `exercises` | Exercise library (regions -> sub-regions -> exercises -> step images), prescriptions and completion | `models.py`, `views.py` |
| `profiles` | Patient profile sections: standing info, medicine, nursing, surgical aids, therapy notes (OT/speech/behavioural), lab tests; plus the read-only physio summary | `models.py`, `rehab.py`, `views.py` |
| `assessments` | Data-driven outcome-measure scales (items, options, score bands), forms (bundles) and recorded results with a snapshot of what was asked | `models.py`, `scoring.py`, `views.py`, `services.py`, `fixtures/scales.json`, `management/commands/load_scales.py` - see [ASSESSMENTS.md](ASSESSMENTS.md) |
| `portal` | Patient dashboard for Client accounts: services, settings, one-time link codes (hashed), account-to-patient links, the read-mostly treatment pages (own template shell `portal/base.html`) | `models.py`, `views.py` - see [PORTAL.md](PORTAL.md) |
| `extras` | The live site's other tables (patient-app analytics, referrals, directory, enterprise, delivery, careers, donations, treatment sessions, visit notes...) as models, plus `live_map.py` / `audit_live_dump` that prove every live column has a home | `models.py` (generated from the live schema), `live_map.py`, `live_schema.json` - see [LIVE_DATABASE.md](LIVE_DATABASE.md) |
| `soapnotes` | Physiotherapy SOAP notes (draft/final/addenda) with metrics and goals shaped like the treatment plan's | `models.py`, `clean.py`, `views.py`, `presets.py` - see [SOAP_NOTES.md](SOAP_NOTES.md) |
| `clinics` | Clinic plan subscription (activated by staff), clinics, team (invited physios + staff), daily queue | `models.py`, `access.py`, `views.py`, `admin.py` - see [CLINICS.md](CLINICS.md) |
| `marketplace` | Public shop **and pharmacy** (one set of views for both, see below), orders | `catalogs.py`, `views.py` |
| `lab` | Public lab-test booking and the lab catalogue | `models.py`, `views.py` |
| `sajhya_health` | Settings, root URLs, landing page, `/healthz/`, error pages, the cross-cutting tests | `settings.py`, `urls.py`, `views.py`, `test_end_to_end.py` |

Dependency direction: `accounts` is the base; `billing`, `exercises`, `profiles` depend on `accounts`;
`profiles` also reads `lab`, `marketplace`, `exercises`. `accounts` reaches into `billing` only lazily (inside
functions) to avoid import cycles.

## Who is the user?

```
User (Django auth)
 └─ Account  (account_type: client | professional | clinic | enterprise)  ── profession / clinic_type / enterprise_type
     └─ ProfessionalProfile   (only for professionals: licence, documents, status draft→submitted→approved/rejected)
         ├─ Patient ──┬─ Visit ─────────────── (completed sessions; one per attended appointment / visit form)
         │            ├─ Appointment (also used for unavailable blocks) ── Task (to-dos belong to the profile)
         │            ├─ TreatmentPlan ─ PlanPhase ─ PlanItem · PlanMeasure ─ PlanReading · PlanGoal
         │            ├─ Prescription ─ PrescriptionExercise  (exercises app)
         │            ├─ PatientPackage ─ PackagePayment · BillingEntry   (billing app)
         │            └─ PatientProfile · MedicineEntry · NursingEntry · AidEntry · TherapyNote · LabEntry  (profiles app)
         └─ BillingEntry, Appointment, Task (by professional)
```

Only **professionals** have a clinical workspace today. Client/clinic/enterprise accounts can sign up and sign in but land
on a welcome page.

## The access rule (read this before adding any view)

All ownership logic is in **`accounts/access.py`**:

- `own_patient(request, pk)` -> `(profile, patient)` or **404** (your own patients **plus** those of clinics you own or work at; see `accessible_patients`)
- `can_see_contact(profile, patient)` -> False for a clinic patient unless you are the clinic owner (use before showing phone/email/address)
- `require_workspace(request)` -> the professional's profile, or **403 until credentials are APPROVED** (use in JSON/POST endpoints)
- `workspace_profile(request)` -> the profile, or `None` unless APPROVED (use in pages; redirect to welcome, which shows the verification status)
- `own_profile(request)` -> profile or 404
- `first_error(form)` -> first validation message (for flash messages)
- `workspace_context(user, profile)` -> header context for workspace pages
- `staff_required` -> decorator for staff-only pages

**Verification gate:** professionals who are not approved (draft, submitted, rejected) get nothing from the workspace. Two layers: `accounts/middleware.py` (`VerifiedWorkspaceMiddleware`, driven by `WORKSPACE_PATH_PREFIXES` in settings - add the prefix of any new workspace area there) and the helpers above.

Every workspace view starts with one of these. Records of other professionals answer **404, not 403**. There is a test
per area that proves another professional cannot read or change a record (search the tests for `stranger`).

## Request flow of a typical page

`urls.py` -> view (decorated `@login_required`) -> access helper -> query scoped to the professional -> template extending
`accounts/pro_base.html` (header, sidebar, shared CSS, `static/js/sajhya-ui.js`).

POST endpoints validate with a Django form, flash a message (`messages`), and redirect back (PRG pattern).
JSON endpoints (`plan_save`, `prescribe`, search endpoints) are used by page scripts with the CSRF header.

## Shared building blocks (use these instead of copying code)

| Need | Use |
| --- | --- |
| Open/close a modal | `data-open="modalId"` on a button, `data-close` on close buttons; modal is `<div class="modal-backdrop" id="modalId">`. Wired automatically by `SajhyaUI.initModals`. |
| Type-ahead search | `SajhyaUI.picker(input, {url, render, onPick, onType})` - endpoint returns `{"results": [...]}` |
| Pick one of my patients | `SajhyaUI.patientPicker(input, hiddenInput, {url, hint, preset})` with endpoint `accounts:appointment-patient-search` |
| Fetch JSON with CSRF | `SajhyaUI.fetchJSON(url, {method, body})` |
| Patient avatar / name cell | `{% patient_avatar p %}`, `{% patient_cell p %}` (`accounts_ui` tag library) |
| Recording a visit (+ last visit + package session) | `accounts.services.record_visit(...)` - **the only place** that does it |
| "Recent patients" | `profile.recent_patients(n)` |
| Exercise thumbnail | `{% exercise_thumb name cover %}` (`exercises/templatetags/exercise_ui.py`) in templates, `SajhyaUI.thumb(name, cover)` in scripts; letter tile when no image |
| Date/time form widgets | `accounts/widgets.py` |
| Shared CSS (buttons, pills, tabs, KPI cards, chips, badges, mini-forms) | defined once in `pro_base.html` - do not redefine in a page |
| Photos | `accounts/images.py: normalize_photo` (validate, resize, strip metadata) |
| Private files | `accounts.models.get_private_storage` (never web-served; served by a permission-checked view) |

`sajhya_health/test_javascript.py` syntax-checks all inline scripts and `static/js/*.js` on every test run.

## Page layouts and styling (three families)

| Family | Template | Used by | Styling |
| --- | --- | --- | --- |
| **Workspace** | `accounts/pro_base.html` | dashboard, patients, appointments, plans, billing, exercises, profile | CSS inline in the template (shared components defined once there); `static/js/sajhya-ui.js` |
| **Sign-in** | `accounts/auth_base.html` | sign in, forgot / reset password pages | `accounts/static/accounts/auth.css` - self-contained, no Bootstrap; split layout (brand panel on wide screens, card only on tablet/phone); field markup in `_auth_field.html`, show/hide-password script in the base |
| **Public card pages** | `accounts/base.html` | package page, signup, onboarding, review, welcome, password change | vendored Bootstrap + Font Awesome (`static/vendor/`), `accounts.css` (header bar, cards), plus `package.css` for the package page (desktop-first: 4 columns, 2x2 below 960 px, 1 column below 600 px) |

Marketplace, pharmacy and lab pages use `marketplace/base.html` + `static/css/marketplace-store.css`.

**No CDN dependency for app pages.** Bootstrap 5.1.3 and Font Awesome Free 6.0 are bundled (`static/vendor/README.md` has
the licences and upgrade steps). **Logo**: `static/images/icon.png` (1254 px original) -> circular `logo-64/128/256.png` and
`favicon.png`; use the small ones in pages (the original is 546 KB). To regenerate them after changing the logo:

```python
from PIL import Image, ImageDraw
src = Image.open('static/images/icon.png').convert('RGB')
cx, cy, r = 627, 622, 548                       # the circle inside the original artwork
crop = src.crop((cx - r, cy - r, cx + r, cy + r))
mask = Image.new('L', crop.size, 0); ImageDraw.Draw(mask).ellipse((0, 0, crop.size[0] - 1, crop.size[1] - 1), fill=255)
crop = crop.convert('RGBA'); crop.putalpha(mask)
for size in (64, 128, 256):
    crop.resize((size, size), Image.LANCZOS).save(f'static/images/logo-{size}.png', optimize=True)
crop.resize((48, 48), Image.LANCZOS).save('static/images/favicon.png', optimize=True)
```

## Pricing and throttling

`billing.PatientAllowance` / `SlotOrder` (professional patient slots) and `clinics.ClinicMonthlyUsage` + `clinics/usage.py` (clinic monthly
enrolment and dues) implement the rules in [PRICING.md](PRICING.md); numbers come from settings. `sajhya_health/throttle.py` rate-limits public forms.

## Things that are derived, not scheduled

No background jobs exist. These are computed from dates when shown: package *Expired/Completed*, medicine *Completed*,
appointment `next_appointment` (resynced on each change), plan "Week X of Y", follow-up reminders. If a value looks stale,
the data it derives from is what changed.

## Storefronts (marketplace + pharmacy)

`marketplace/catalogs.py` defines a `Catalog` (model, session cart key, URL names). The same views and templates serve both;
routes in `marketplace/urls.py` pass `{'catalog': 'marketplace'|'pharmacy'}`. Templates use `{% url catalog.urls.cart %}`
instead of hard-coded names. To add a third storefront: a model, a `Catalog`, a block of routes. Orders are
`marketplace.Order` with `order_type`. Order confirmation pages are visible only to the buyer's session (and staff).

## Time and money

- Time zone `Asia/Kathmandu`; datetimes stored UTC. Compare datetimes with ranges (`start__gte/lt`), **not** `__date`
  lookups (MySQL needs time-zone tables for those).
- Money is `DecimalField` NPR. Totals that come from a form are **never trusted**: amounts are recomputed on the server.

## URL map (prefix `accounts/` unless noted)

| Area | URLs |
| --- | --- |
| Public | `/` landing, `package/` plans, `signup/...`, `login/`, `password/forgot/`, `/marketplace/`, `/marketplace/pharmacy/`, `/lab-tests/`, `/healthz/` |
| Onboarding | `professional/step/N/`, `profile-photo/`, `welcome/`, staff: `review/`, `review/N/` |
| Workspace | `dashboard/`, `patients/`, `patients/N/` (tabs: overview, plan, profile, exercises, visits, billing, notes, documents), `patients/N/edit/`, `patients/N/photo/...`, `appointments/`, `plans/`, `plans/N/` |
| Billing | `/billing/` (daily book), `/billing/packages/` |
| Exercises | `/exercises/`, `/exercises/prescribe/` |
| Profiles | `/profiles/patients/N/<section>/add/` etc. |
| Patient dashboard | `/portal/` (home), `plan/`, `exercises/`, `advice/`, `services/`, `settings/` (linking), physio side `/portal/invite/N/`, `/portal/revoke/N/` |
| SOAP notes | `/soapnotes/patients/N/new/`, `/soapnotes/N/` (tab: `patients/N/?tab=soap`) |
| Clinics | `/clinics/` (hub), `/clinics/N/?tab=overview|team|patients|queue|settings` |
| Assessments | `/assessments/patients/N/new/`, `.../fill/`, `/assessments/sessions/N/` (tab: `patients/N/?tab=assessments`) |
| Passwords | `password/forgot/`, `password/reset/<uid>/<token>/`, `password/change/` |

## Recipes

### Add a section to the patient Profile tab
1. Model in `profiles/models.py` with `patient` FK and `RecordedByMixin`; `makemigrations profiles`.
2. A `ModelForm` in `profiles/forms.py` (validate in `clean()`).
3. Register in `SECTIONS` (`profiles/views.py`) - the generic `add`/`delete` endpoints then work.
4. Add the key to `SECTION_ORDER`, a count/label in `profile_context`, and a block in `profiles/templates/profiles/_profile.html`
   plus an add-modal in `_modals.html`.
5. Add tests to `profiles/tests.py` (add, validation, delete, privacy).

### Add a catalogue (like pharmacy / lab) used by profiles
Model + admin + `load_*` command reading a `fixtures/*.json` + a search endpoint returning `{"results": [...]}`; in the
modal call `SajhyaUI.picker`. The profile entry stores an optional FK **and** a free-text name so it works without the catalogue.

### Add a workspace page
View with `@login_required` + an access helper; template `{% extends 'accounts/pro_base.html' %}` with `active` in context
(highlights the sidebar); reuse the shared CSS and `SajhyaUI`; add a sidebar link in `pro_base.html`; add tests
(including a "stranger" test).

### Change what a plan (package page card) contains
Admin -> Billing -> Plans. No code change. Prices, trial text and patient limits are data.

### Add a new account type behaviour
`Account.account_type` is chosen at signup. Clinical features check `own_profile` (professional only). A clinic or
enterprise workspace would be new views gated on their own profile model; nothing existing needs to change.

## Testing

```
python manage.py test                       # everything (~12 s, in-memory SQLite)
python manage.py test accounts billing      # some apps
python manage.py test sajhya_health.test_end_to_end
```

Test helpers: `accounts/tests/helpers.py` (`make_professional`, `make_patient`, `private_storage()` which redirects uploads
to a temp folder). Lockout is off in tests (`AXES_ENABLED = not TESTING`); the lockout test turns it back on.

## Show / hide password

`static/js/pw-toggle.js` adds an eye button to every `input[type=password]` (sign-up, change password, clinic login, staff logins). The sign-in page keeps its own `data-pw-toggle` button, which the script leaves alone. New templates with a password box only need to load the script (the three base templates already do).

## Advance payments

`billing.PatientAdvance` is a signed ledger per patient (advance taken +, used for a bill -, refund -, returned to balance +); the balance is its sum. A bill settled from the advance gets an `EntryPayment` with mode `advance`, which is **not** counted as money taken (the cash was counted when the advance was taken, and refunds count as money paid out). Cancelling or correcting a bill puts what it took back into the balance.

## Sending a bill (invoice)

`billing/invoice.py` builds the PDF (reportlab, pure Python, so it installs on cPanel from `requirements.txt`) and the share links. The invoice page (`/billing/entry/N/invoice/`) offers download, print, WhatsApp (`wa.me` with the message and a link; local numbers get `DEFAULT_COUNTRY_CODE`, default 977), the phone share sheet, copy link and e-mail (PDF attached, through the normal e-mail settings). The link sent to the patient is signed with Django `signing` and expires after 90 days; it needs no sign-in and opens that one PDF only. The built-in PDF fonts are Latin: a patient name or service in Nepali script is left off the PDF (patient ID is printed instead) and shown in full on the online invoice.

## WhatsApp messages and notices

`accounts/messaging.py` holds the built-in wording (appointment booked / reminder / rescheduled / cancelled, follow-up, bill) and fills `{placeholders}`; a professional's own wording is stored in `MessageTemplate` (built-in messages they changed, plus custom notices). `accounts/notices.py` is the **Messages** page (business WhatsApp number, editors with live preview, custom notices) and **Send a notice** (a group of patients, each with a `wa.me` link and their own text). Nothing is sent by the server: the professional presses send in WhatsApp, from whichever WhatsApp account is open on their device. The business number (`ProfessionalProfile.whatsapp_number`) is printed in messages and on invoices. Sending automatically from that number would need the WhatsApp Business API (a paid Meta service), which is not built.
