# Decisions, findings and open items

A record of *why* things are the way they are, written when the owner was unavailable and the choices had to be made
independently. If you disagree with one, the "How to change it" line says how.

## The last batch of work (six tasks)

### 1. Patient profile pictures
- **Stored privately, not in public `media/`.** A patient picture is personal data of a (possibly sick) person. It lives in
  `PRIVATE_MEDIA_ROOT/patients/<professional id>/<random>.jpg` and is only served by a permission-checked URL
  (`patients/N/photo/<name>/`), so a guessed link or a search engine can never reach it.
  *How to change it:* point `Patient.photo` at the default storage (and drop the view) if public pictures are acceptable.
- **Every upload is normalised**: validated as a real image, rotated upright, flattened to RGB, metadata (GPS, device) stripped,
  longest side 640 px, saved as JPEG. This also defuses renamed files and "image bombs". Replaced/removed pictures are deleted
  from disk.
- **One avatar tag everywhere** (`{% patient_avatar %}`): patient list, dashboard, quick access, patient page header -
  so there is one place to change how a picture is shown. Initials show when there is no photo.
- The professional's own profile picture was left as it was (public media, shown in the header).

### 2. Lab tests and pharmacy on the landing page
- **Copied from the old project**: 33 lab tests, 10 panels, 35 pharmacy products (+ their 35 images). Loaded by
  `load_lab_catalog` / `load_pharmacy` and managed in the admin afterwards.
- **Lab test prices are the old project's placeholder prices** (its own comments say "review and reprice before real use").
  Please review them in Admin -> Lab tests.
- **Pharmacy products came without prices (0.00)**, so the storefront shows "Price on request" and an order's total reads
  "To be quoted". Set prices in the admin when known.
- **One storefront code, two catalogues.** Instead of copying the marketplace views/templates for the pharmacy, both run on the
  same code (`marketplace/catalogs.py`). Less code to keep in step; a fix to the cart fixes both.
- **Guests can book lab tests** (no login), as before. The confirmation page is private to the booking browser (and staff)
  because request numbers are guessable - same rule applied to shop orders after the audit.
- **Landing page links**: Pharmacy and Lab Tests cards, nav and footer now go to real pages. "Find a Physio" and "Clinical Tools"
  were pointed at sign-in / the package page as the closest real destinations. Other placeholders on the landing page
  (Doctors, Tools, About, Careers, Donate, Summit...) are still `#` - those features do not exist in this project.
- Two different pharmacy products are both named *Pantoprazole*; the loader therefore keys on **name + image**.
- **Used in profiling**: the patient's Medicine section searches the pharmacy catalogue; the Lab section searches tests and panels
  (both with a free-text fallback).

### 3. Patient profile sections (new `profiles` app)
- Sections: **General** (allergies, history, standing care needs), **Medicine**, **Nursing**, **Surgical aids**, **Rehab**
  (Physiotherapy / Occupational / Speech / Behavioural), **Lab tests**.
- **Physiotherapy is read-only and pulled from the daily records** (visits, treatment-plan measures and interventions, exercise
  prescriptions) in `profiles/rehab.py`, exactly as requested - nothing is typed twice, so it can never disagree with the plan.
- **Occupational, speech and behavioural therapy are typed notes** (goal, what was done, response, plan). The old project did
  not actually contain these (only shop categories), so the fields are a minimal, conventional session-note shape.
- **Medicine**: when-to-take is four tick-boxes (morning/afternoon/evening/night); "Completed" is derived from the end date.
- **Nursing**: structured vitals; readings outside common adult ranges are marked with a warning symbol. This is a prompt to
  look, not a diagnosis, and the thresholds are in `NursingEntry.needs_attention` if clinicians want different numbers.
- **Lab tests**: advised -> booked -> sample collected -> result (value, unit, range, rating, optional PDF/image report).
  Reports are private files, like credentials.
- **Allergies show as a red line under the patient's name on every tab** - a safety signal should not hide inside one tab.
- Entries record who made them (`recorded_by`). There is no patient login yet, so only professionals edit these.
- **Also added**: a "sessions completed" counter on the patient page.

### 4. Account and professional-package audit
Everything from signup to billing was walked end to end (see `sajhya_health/test_end_to_end.py`) and re-run against the real
MySQL database. Bugs found and fixed during the audit:
1. Signup crashed once login-lockout was added (needs an explicit auth backend when logging in after signup).
2. A failed prescription (only exercises that no longer exist) left an empty prescription behind and superseded the real one.
3. The plan page returned "not found" for Client accounts (they have no professional profile).
4. Order confirmation pages were readable by anyone who guessed an order number.
5. Replacing or removing a patient picture left the old file on disk (found while testing; now deleted).
6. The treatment-plan page made ~31 queries (now 16).

**"Billing package against completed sessions"** works like this: a package (1/2/3/4 weeks, N sessions, price, instalments) is
consumed by *completed* sessions. A session is completed when a visit is recorded through the visit form **or** an appointment
is marked attended (both go through `accounts.services.record_visit`). Each completed session uses one session of the patient's
oldest *Active* package; a completed, expired (past its weeks) or cancelled package is never charged, so a 4th session on a
3-session package does not go negative. Visits created directly in the admin do not use sessions.

### 5. Removing repeated code
Consolidated, with tests proving nothing changed:
- Access helpers (`accounts/access.py`) replaced six near-identical private helpers across five apps.
- The visit side effects (visit + last-visit date + package session) existed in two places; now `record_visit`.
- Patient search dropdown (4 copies), modal open/close (6 copies), ICD and exercise type-ahead -> `static/js/sajhya-ui.js`.
- CSS for pills, tabs, KPI cards, chips, badges, mini-forms (5 copies each) -> once in `pro_base.html`.
- Patient avatar / name cell / recent-patients query / date widgets -> one definition each.

Deliberately **left as is**: the patients page keeps its own "Quick Access" search box (it is in the approved mock-up and
posts to the same search), and each form keeps its own validation (the rules differ).

### 6. Forgot password
- **Emailed one-time link, valid 1 hour** (Django's default is 3 days - too long for a clinical system), single use.
- **The "check your email" page is identical whether or not the address exists**, and a mail-server failure is logged, not
  shown - so the form cannot be used to discover who has an account.
- **Throttled**: 5 requests per IP per hour (counters in a file cache so every worker process shares them).
- **Emails must now be unique** per account (case-insensitive) so a reset can only mean one account.
- A successful reset **clears any sign-in lockout** for that user, and **change password** (signed in) signs out other sessions.
- In development the email is printed in the console - copy the link from there.
- *Check these two accounts:* **`DrPrazzol`'s email is `aetheticphysiox@gmail.com`** (looks like a typo of
  "aestheticphysiox") so a reset would go nowhere - fix it in Admin -> Users. **`prazzol`** (superuser) has **no email**; set one
  or use `python manage.py changepassword prazzol`.

## Sign-in page, package page and logo (latest batch)

- **Root cause of the "unstyled sign-in page"**: the pages loaded Bootstrap and Font Awesome from public CDNs; when the
  browser could not reach them the page fell back to bare HTML. **Both libraries are now bundled with the site**
  (`static/vendor/`), so app pages work offline, load faster and do not leak visits to third parties - a better fit for a
  medical product. (Landing, shop, pharmacy and lab pages still request Google Fonts, which is optional decoration.)
- **Sign-in page**: split layout (brand panel with three selling points on wide screens; just the card on tablet and phone),
  icon fields, show/hide password, errors in a banner. **Forgot password, Get started and Home are real buttons** as requested
  (soft, outlined and neutral so "Sign in" stays the obvious primary action). The password-reset pages reuse the layout.
  It uses no Bootstrap, so one stylesheet (`auth.css`) controls it.
- **Package page**: rebuilt desktop-first - four equal plan cards in one row (up to 1280 px wide), a "Most popular" ribbon and a
  stronger button on the Professional plan, prices big and grouped (`NPR 1,000 / month`), a comparison table; 2x2 on tablet,
  one column on phone. The "Most popular" choice is a design decision, not data: change it in `package.html` if another plan
  should be highlighted. Plan content still comes from Admin -> Plans.
- **Logo**: the existing Sajhya mark (the carved window with the "H") is used as a round logo in the workspace header (every
  dashboard page), the public header bar, the sign-in page, shop/pharmacy/lab headers and the landing page, plus the browser
  tab icon. Small generated versions are used so pages no longer download the 546 KB original.
- Pages were checked visually in a headless browser at desktop, tablet and phone widths.

## Platform decisions made earlier (still true)

- **Tests use in-memory SQLite**, because the app's MySQL user cannot create a test database (good practice). Production
  runs MySQL. The end-to-end journey is additionally re-run against MySQL by hand after big changes.
- **Production refuses to start unsafe** (weak key, no hosts, no DB) rather than limping along.
- **Static files are served with plain file names** (WhiteNoise `CompressedStaticFilesStorage`, no hash manifest). The old
  project hit stale-manifest 404s because image paths are stored in the database; plain names avoid that class of failure.
- **Derived instead of scheduled**: statuses are computed from dates, so there is nothing to run in the background and nothing
  to go stale when a job fails.
- **Credential verification gates everything (stricter than before)**: until a professional is approved, *no* workspace
  feature works - not even the dashboard or Add patient. Earlier, a submitted application could already use the workspace
  with a banner. Unapproved users see only the status page (continue onboarding / under review / rejected with reason).
  Enforced twice (middleware by URL prefix + access helpers) so a forgotten check in a new view still fails closed.
- **Exercise thumbnails**: small pictures (first step image, else the main image) on prescribed-exercise rows, the rehab
  summary, library cards/prescribe sheet and the plan-builder search. Exercises without a picture get a letter tile
  rather than an empty gap.
- **"Recent patients" means recently added, opened or seen** (not only patients with a recorded visit, which left the list
  empty for new users). `Patient.last_activity` is set on creation, whenever the patient page is opened (`touch()`), and when
  a visit is recorded. Empty only when the professional has no patients.
- **Aids are searchable from the marketplace** (`Product`, not the pharmacy); the free-text name still works. The link is
  `AidEntry.product`.
- **Reports** (`accounts/reports.py`): one builder returns KPIs + table sections, rendered as HTML and CSV from the same data.
  Definitions: *seen* = has a visit in the period; *new client* = first-ever visit is in the period, otherwise *follow-up*; age
  is on the last day of the period; weeks start on **Sunday** (Nepal); money = billing book + package payments. Age/sex tables
  are aggregates with no names, shaped like facility (HMIS) returns. A direct push to Nepal's HMIS (DHIS2) is **not built**: it
  needs the ministry's credentials and data-element IDs. To add: map the section counts to those IDs in a new module.
- **Settings**: a professional can change contact details, photo, experience, focus areas/services, practice details, default
  appointment length and email. **Name, title and licence details are read-only** because staff verified them; a correction
  needs a staff re-check (change them in the admin). Notification preferences were not added: nothing sends SMS/email
  reminders yet. The practice name and facility code print on reports.
- **Assessments are a separate, data-driven app**: scales/items/bands/forms live in the database (admin or `load_scales`), so
  they can be added, changed or retired without code. Results store a *snapshot* (name, version, every question and answer),
  so changing a scale never rewrites history. Several scales can be recorded in one sitting ("session"); one session may mix
  scales from different forms. Item wording for long instruments (Berg, ODI, SARA) uses general grade anchors, not the full
  published text, to avoid reproducing copyrighted material; clinicians grade against the official instrument. FIM is
  trademarked - ship with a licence note and make it easy to deactivate. Per-muscle/side scales are one assessment each.
- **Pricing (Professional / Clinic)**: Professional gets 10 free patients, then pays NPR 200 per extra patient by buying **slots**
  in advance (paid slots stored on `PatientAllowance`; staff add them when the order is marked paid) - chosen over blocking-until-
  subscription because there is no monthly fee and it matches "200 for each patient". Clinic patients are exempt from the
  professional count. A clinic gets 400 newly enrolled patients per calendar month; each one above is **a due, never a block**
  (`ClinicMonthlyUsage`), settled before the next billing. Rows stay editable until paid, then freeze. Everything is manual
  money handling by staff until a payment gateway exists. Existing over-limit professionals were grandfathered with pre-paid slots.
- **QA is part of the test suite**: `sajhya_health/test_qa.py` sweeps every URL/role, links, XSS, GET-safety and query budgets, so new
  pages are checked automatically; MySQL-specific checks live in `scripts/qa_mysql_*.py`.
- **Orders and lab bookings are linked to accounts**: lab bookings gained a `user` field (marketplace/pharmacy orders already had
  one, used when signed in). The dashboard lists them with status. Guest orders attach automatically when the same browser signs
  in/up, or by claiming with order number + email; never by email alone (emails are unverified). Chosen so lab results and
  order history can later be shown only to the owner on any device, instead of relying on a short per-browser session list.
- **Patient dashboard (revised)**: the dashboard belongs to the *Client account*, not to a linked record, so a client with
  nothing linked still gets Pharmacy / Marketplace / Lab tiles; linking a treatment record moved into **Settings** (as
  requested) and the welcome page no longer carries it. The layout is a desktop-first web app (fixed left menu, wide
  two-column content) that degrades to a top menu on small screens, instead of a phone-only column. Storefront pages stay
  public and show a back link for signed-in clients. Orders/lab bookings are not listed in the dashboard because they are not
  tied to accounts yet.
- **Patient portal sign-in**: Client account + **one-time code from the physio + date of birth**, not the patient code. The
  patient code is on paperwork and guessable, and no SMS/OTP gateway exists, so a hand-delivered single-use code is the
  strongest thing available today; it is hashed at rest, expires in 7 days, dies after 5 wrong birth dates, and accounts are
  throttled. One account per patient record, many records per account (parents). The patient sees only *published* material:
  active plan, active prescription, and the plan's education (Do) and precautions (Don't) text; never notes, SOAP, billing or
  contact details. Patients can tick exercises and report how they felt; the physio sees it. A phone-OTP login could replace the
  code once SMS exists.
- **SOAP notes**: a separate app, placed right after Overview. Metrics and goals are stored as JSON in the *same shape* as the
  treatment plan builder, so a new plan pre-fills from the latest note that has them (opt-out `?from_soap=none`). Notes are
  draft -> final (locked) with dated addenda, because a clinical record should not be silently rewritten; authors edit/delete
  only their own drafts; final notes cannot be deleted in the app. The note can also record a visit (optional tick) so the
  same entry does not need typing twice. Free text stays free: suggestion lists only help typing.
- **Clinic patients are shared, contact details are not**: a patient registered inside a clinic belongs to the clinic team
  (every active physio can view and treat them); the phone/email/address are visible to the clinic owner only, enforced in the
  patient page, edit form, lists, searches and billing. The Clinic drop-down on patient forms was removed: the clinic can
  only be set by the clinic's own *Add patient* button, shown as fixed text. When a physio leaves, patients they registered
  there pass to the owner. Chosen over "tagging a private patient" because the clinic needs continuity and the owner, not each
  physio, holds the patient relationship. Invitations are surfaced as a sidebar badge, dashboard banner and hub section.
- **Clinic registration (revised)**: "Register a clinic" requires signing in with a professional account, then shows the full
  five-section profile form; submitting it creates the clinic, requests the Clinic plan automatically and opens the clinic
  dashboard. Required: name, primary phone, province, district; everything else can be completed later (a completeness meter
  nudges). A clinic is *usable* (team, queue, patient tagging) only while its owner's Clinic plan is active, so the form
  can be filled before payment but nothing operational works until staff activate. The old standalone "Clinic" signup now
  redirects to this flow. Logo/banner are public images (shrunk; banner cropped to 16:9). A public clinic page / directory
  was not built, but the data is there for it.
- **Clinic accounts are an upgrade of a professional, not a separate account type**: one login, one workspace; the Clinic
  plan unlocks Clinic Connect (`ClinicSubscription`). With no online payment, an upgrade is a request that staff activate in
  the admin after arranging payment (action buttons; optional expiry; per-professional clinic limit). Physios join by
  **invitation + acceptance**, only if verified; staff are records without logins (a later phase could add staff sign-ins).
  Patients stay private to their physio; the clinic gets the queue (needed at the front desk) and counts only. Clinic-level
  billing/appointments were left out for now.
- **Records of other professionals answer 404** (not 403) so existence is not revealed.
- **Billing "packages" are patient session packages** (1-4 weeks). **Account plans** (Client/Professional/Clinic/Enterprise)
  are only the content of the package page and the 500-patient limit; paying for an account plan inside the app was built and
  then removed on request.
- **Time zone Asia/Kathmandu**, and datetime filtering by ranges (MySQL has no time-zone tables by default).
- **Exercise library**: 788 exercises copied; only ~243 have pictures because that is all the old repository contained.

## Known gaps and open questions

| Item | Status / suggestion |
| --- | --- |
| Patient-facing login (patients seeing their plan, tick off exercises, upload their own pictures) | Not built. Needs a patient account model and consent rules. Everything is currently professional-entered. |
| Clinic and Enterprise workspaces | Those accounts sign in but land on a welcome page. Prices are "custom" until set in the admin. |
| SMS / email reminders, payment gateway (eSewa/Khalti) | Not built. Email infrastructure is configured (used by password reset). |
| Expired plan enforcement | Plans only enforce the patient limit; nothing locks an expired account. |
| Static image weight (~330 MB) in the repository | Consider Git LFS or an object store/CDN. |
| `landing.html` structured data (JSON-LD) and og:image point at `sajhya.com` | Copied from the old site; change if this deployment has another domain. |
| Lab prices, pharmacy prices | Placeholder / missing - set in the admin before real use. |
| Old project's patient data, prescriptions and orders | Not migrated (different patient model, no mapping). Catalogues were migrated. |
| Files are not encrypted at rest | Use an encrypted volume if your policy requires it. |
| Exercise Nepali descriptions | The old database had none. |
