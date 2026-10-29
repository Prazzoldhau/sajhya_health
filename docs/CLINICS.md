# Clinics ("Clinic Connect")

A verified professional can **upgrade to the Clinic plan** and then create clinics, build a team and run an on-site queue.
They keep their normal professional workspace; Clinic Connect is one more item in the sidebar (between Billing and Reports).
Code: the `clinics` app. Ported from the old project's `clinic_account` app, with the weak points fixed (see "What changed").

## The journey

1. **Start**: the Clinic card on the package page (or *Register a clinic* in Clinic Connect) goes to `/clinics/register/`.
   Visitors who are not signed in are sent to **sign in with their professional account** (no professional account yet? sign
   up as a professional first) and, once signed in, land directly on the **clinic registration form**. Only professionals whose
   credentials are *approved* can reach it.
2. **Registration form** (five sections; only name, primary phone, province and district are required, the rest can be
   completed later from the dashboard):
   1. Basic information: name, short bio (500 characters), logo (max 2 MB, shrunk to 512 px), banner (cropped to 16:9, 1280x720)
   2. Legal and registration: business registration number (PAN/VAT/company), health facility licence number, specialisations
   3. Contact and location: primary and secondary phone, official email, website, province (the 7 provinces), district/city, ward/street, map link
   4. Hours and slots: opening and closing time for each day (Sunday-Saturday) and the default slot length (15/30/45/60 min)
   5. Amenities: wheelchair access, private rooms, gym area, parking, digital payments
3. **Submitting** creates the clinic (code like `CLI-A3F9K2`), **requests the Clinic plan automatically** (there is no
   online payment yet) and opens the **clinic dashboard**. Until the plan is active the dashboard shows "Registration
   received", the profile can be completed, and Team / Patients / Queue show "Waiting for plan activation". Only one pending
   clinic is allowed before activation.
4. **Activation (staff)**: Django admin -> Clinics -> Clinic subscriptions -> select the request -> action
   **Activate Clinic plan for 1 year** (or *no expiry*, or *Decline*; put a reason in *Staff note* first and it is shown to
   the professional). Activation unlocks all of that professional's clinics at once. `clinic_limit` (default 3) is the number of
   clinics they may then have. The price shown comes from Billing -> Plans -> Clinic.
5. **Clinic dashboard** (`/clinics/<id>/`): profile completeness meter with what is still missing, about/hours/specialisations,
   team size, patients, today's queue counts and visits per physio this month. Tabs: Overview, Team, Patients, Queue, Clinic
   details (owner only: the same five-section form, to complete or change anything).
6. **Team and the invitation channel**: the owner searches *physios* by name, username or licence number (only physios with
   **verified credentials** appear; licence shown masked) and sends an **invitation**. The physio is told in three places: a
   red badge on **Clinic Connect** in the sidebar, a banner on their dashboard, and an **Invitations** section at the top of
   Clinic Connect. Accepting makes them an active member (declining or leaving is always possible). *Staff* (manager,
   receptionist, assistant, other) can be given their own login (see "Staff logins" below).
7. **Working at a clinic (physio view)**: Clinic Connect lists **Clinics I work at** (owner, joined date, number of clinic
   patients, buttons *View patients* and *Queue*) and **Previous clinics**. From the clinic's **Patients** tab a physio
   opens any clinic patient and **treats** them: visits, treatment plans, exercise prescriptions, assessments, profile entries.
   Each visit records the therapist who did it, so the clinic can see who treated whom.
8. **Adding a patient inside a clinic**: only from the clinic's own *Add patient to <clinic>* button. The clinic is shown as
   **plain text (not a drop-down)** and cannot be changed; a normal patient (added from the Patients page) belongs to no
   clinic. Clinic patients do not count against the 500-patient limit.
9. **Queue**: add one of the *clinic's* patients to today's queue, **Call in**, **Done**, **Cancel**; every team member can work
   it. The queue search returns names and IDs only.

## The clinic's own login and workspace

Each clinic can have a sign-in of its own, chosen by the **owning physiotherapist** (Clinic workspace > *Clinic details* > *Clinic login*: a username and
a password; they can change both at any time, and only they can).

- The clinic login is a normal user (account type *clinic*) whose workspace profile belongs to the clinic. It opens the **full professional workspace**:
  Dashboard, Patients, Appointments, Treatment plans, Exercise library, Billing, Reports, Settings - all with the clinic's **own** data, separate from the
  physiotherapist's. Assessments, SOAP notes and results work from the clinic's patients.
- The sidebar has **Clinic & team**, which opens the clinic workspace (Overview, Team, Patients, Queue, Clinic details). The clinic login runs the clinic like
  its owner does (team, queue, details), except that it cannot change its own username/password.
- Patients added by the clinic login are registered **under the clinic**: they count toward the monthly cap, the team sees them, and the clinic plan covers them
  (no personal 10-free-patient limit applies to a clinic login).
- The physiotherapist keeps their own workspace and sees the clinic from *Clinic Connect* as before. Staff can switch clinics from the clinic sidebar.
- Technical: `Clinic.workspace` points to the clinic's `ProfessionalProfile` (created by `clinics/login.py`); `clinics_of()` and `clinic_for_member()` treat it as the owner.

In the clinic's *Team* tab, adding people is under **Actions > Add team**: one window with a *Physiotherapist* form (invitation) and a *Staff* form.

## Privacy rules (deliberate)

- **Clinic patients are shared by the clinic team** (owner + active physios), and only by them. Nobody else can open them (404).
- **Contact details are hidden from physios**: phone, email and address of a clinic patient are visible to the **clinic
  owner only**. A physio sees "Contact details are kept private by the clinic": on the patient page, the edit form (the
  fields are not offered, so they cannot be read or overwritten), the patient list, the clinic's patient table, searches
  (you cannot search by a hidden number) and invoices (the number is not copied into billing). This applies even to patients
  that physio registered themself.
- A patient who is *not* tied to a clinic stays private to their physio exactly as before; clinic owners cannot see them.
- When a physio leaves or is removed, the patients they registered in the clinic **pass to the clinic owner**, so the leaver
  has no further access. If the owner's Clinic plan expires, members lose access to clinic patients until it is renewed.
- A non-member gets a 404 for any clinic page or action. Members cannot manage the team or edit the clinic (owner only).
- Posting someone else's clinic id when adding a patient is refused (checked against clinics you belong to and that are active).
- The clinic overview shows counts per therapist (visits, patients), never patient names.

Known limits: appointments and billing for a clinic patient are not shared between physios (record visits from the patient
page; use the queue at the front desk). A physio's treatment plans and prescriptions can be opened and edited by any
colleague at the clinic, because the patient is shared.

## Statuses

| Thing | Values |
| --- | --- |
| Subscription | requested -> active (staff) / rejected; active with an `expires_at` date becomes **expired** automatically (clinics pause, data is kept) |
| Member | invited -> active / declined; active -> left (leaving or removal) |
| Queue entry | waiting -> called -> completed, or cancelled |

## What changed from the old project

Old `clinic_account`: any logged-in user could create a clinic, physios were added without their consent, the queue accepted
any patient id, and queue/patient views were not scoped to the clinic's people. Here: plan gate, invitation + consent,
owner/member checks on every view, own-patients-only queueing, aggregate-only reporting. Push notification when a patient is
called was not ported (patients have no login yet).

## Not built yet (suggestions)

Online payment for the upgrade; staff sign-ins with roles (receptionist-only queue access); clinic-level billing and
appointments shared across physios; per-clinic reports export; calling a patient by SMS.

## Troubleshooting

- *Clinic is "Awaiting plan activation"*: staff have not activated the subscription yet (admin action above).
- *Register button does nothing / goes to sign-in*: the user is not signed in, or is not an approved professional.
- *"You have reached the number of clinics your plan allows"*: before activation one clinic is allowed; afterwards `clinic_limit`.
- *Physio not found when inviting*: they are not approved, already on the team/invited, or it is the owner themself.
- *Invitation not visible to the physio*: it appears at the top of **their** Clinic Connect page.
- *A physio cannot see a phone number*: by design (see Privacy rules). Ask the clinic owner.
- *A physio lost access to a clinic's patients*: they left/were removed, or the owner's Clinic plan expired.

## Staff logins and the front desk

In the Team tab, each staff row has **Give a login**. The owning physiotherapist picks a username and password for that person
(same password rules as everywhere; usernames are unique) and can change them at any time. Removing the person from the team
also stops them signing in. Staff sign in at the normal login page and land on the **front desk** (`/clinics/desk/`). They have no
physiotherapist workspace and never see clinical records (diagnosis, notes, treatment, billing).

| Role | Overview | Patients (names/IDs) | Phone numbers | Register patient | Queue |
|---|---|---|---|---|---|
| Manager | yes | yes | yes | yes | add, call, done, cancel; plus team list |
| Receptionist | - | yes | yes | yes | add, call, done, cancel |
| Therapy assistant | - | yes | no | no | call, done (cannot add or cancel); **records the treatment given and the exercises supervised** (Record treatment tab) |
| Other staff | - | - | - | - | view only |

Patients a staff member registers belong to the clinic (they count toward the monthly cap) and to the owning physiotherapist's team.
The queue and registration pause while the Clinic plan is not active. Staff logins have no email, so a forgotten password is reset
by the owner from the same button.

### Front desk: billing, who registered, age

- Managers and receptionists have a **Billing** tab at the front desk: bill a clinic patient (paid / part paid / credit / from advance, with the cash-handed-over carry-over), receive payments on credit, download the PDF or open WhatsApp. Bills are kept in the clinic's own workspace (its login when it has one, otherwise the owner) and each shows **who billed**. Staff cannot edit or cancel a bill; the owner or the clinic login can.
- Every patient records **who registered them** (name and role: Physiotherapist, Clinic login, Receptionist, Manager...). It shows in the clinic Patients tab, the front desk list and the clinic login. The clinic's own login sees all of the clinic's patients in its workspace, including those reception registered.
- A patient can be registered with an **age** when the date of birth is not known; the date is then an estimate and the age is shown as approximate. A real date of birth always wins.

## Business owners

A business owner owns and registers clinics but does not treat patients. They sign up as a **professional** and choose **business owner** in place of a health profession (`Profession.is_business_owner`, added by migration `accounts/0027`).

- **Onboarding:** Account, **Business** (registered business name, business registration number, PAN / tax number, registering office), **Documents** (owner ID, business registration certificate, PAN / tax certificate), then Review. There is no licence, degree or practice step.
- **Verification:** staff review it on the same applications page, which shows the business details and both certificates. The files are private, like the other credential documents.
- **After approval:** the owner lands on Clinic Connect (no dashboard, patients, billing or reports of their own) and registers clinics exactly as a physiotherapist does. The Clinic plan is still activated by staff, and each clinic then gets its own login and team.

## Modules per clinic

Staff choose which parts of the workspace each clinic has: **Appointments**, **Billing & accounts**, **Assessments & SOAP notes**, **Treatment plans & exercises**, **Messages & notices**, **Reports** (`clinics/modules.py`). Patients, queue, team and settings are always included.

- **Where:** Django admin, Clinics, open the clinic, tick the modules (`Clinic.modules`). New clinics start with every module on.
- **Effect on the clinic's own login:** a module that is off disappears from the menu and its pages redirect to the clinic with a message (forms and scripts get a 403). Enforced in `accounts/middleware.py`.
- **Effect on the front desk:** with Billing off the Billing tab and its actions disappear for every role (`ClinicMember.can`).
- **Not affected:** an owning physiotherapist's personal workspace. The clinic owner sees what is on and off in the clinic Overview.

## Departments on appointments

A practice or clinic workspace can list departments (Physical Therapy, Occupational Therapy...) under Appointments, Manage (`/accounts/appointments/departments/`). Each appointment can be booked into one; the calendar shows it on the appointment, colours it, and can filter by department, so patients at the same time in different departments sit side by side. Removing a department keeps its appointments, only the label goes.

## Schedules: a page for each department and therapist

Appointments on a clinic's calendar can be booked **with** a therapist or assistant (`Appointment.practitioner`, a clinic team member) and into a department. Everyone reads the same appointments; what changes is the filter.

- **Department login:** Team, Add team, Staff, role *Department login*, choose the department, then *Give a login*. It shows only that department's appointments on the front-desk Schedule tab (no phone numbers, no clinical records, nothing else). Its password may be short and simple (4+ characters, not the username); repeated wrong guesses still lock it out.
- **Front desk:** managers and receptionists see the whole clinic and can narrow to a department; a therapy assistant starts with the appointments booked with them (Show everyone to widen).
- **Therapist:** a physiotherapist on a clinic's team gets **My schedule** in their menu, across every clinic they work at.
- Turning the Appointments module off for a clinic also removes the Schedule tab.

### Visiting doctors and therapists who are not on Sajhya

Add them under Team, Add team, Staff with the role **Doctor / therapist** and a specialty (for example Ortho). They are bookable ("Book with") and shown as *Dr Sailendra Maharjan (Ortho)*. With *Give a login* they sign in to the front desk: Schedule opens on their own appointments, and like a therapy assistant they can call patients and record the treatment given and exercises supervised, stamped with their name and the role *Doctor / therapist*. No phone numbers and no billing. If they later join Sajhya they can be invited as a physiotherapist; their earlier appointments stay on the staff record (they are not moved across automatically).

### Reception runs the appointment book

Receptionists and managers (not assistants, doctors or department logins) can **book, change and cancel** the clinic's appointments from the front desk: Schedule tab, *Book an appointment*. They pick one of the clinic's own patients, the date, time and length, and optionally a department and the therapist it is with. After booking, changing or cancelling they get the same WhatsApp / Viber / SMS message buttons as the clinic login. Reception does not mark an appointment attended, because that records a clinical session. Needs the Appointments module and an active Clinic plan.

### The front desk as a workspace

The front desk has a sidebar like the main workspace. Receptionists and managers open on a **Dashboard**: appointments today (to come / attended), the queue, patients registered today, what was billed and received today and what is still to collect, who is coming up next, who is in the queue, and quick buttons (book, register, add to queue, new bill). Assistants and doctors see no money. The **Schedule** tab is a **calendar** (1, 3 or 7 days, departments side by side, a department filter): click an empty time to book, click an appointment to change it, cancel it or send the patient a message. A **List** view shows the same day as a table. A department login gets the same calendar read-only, without phone numbers or message links.
