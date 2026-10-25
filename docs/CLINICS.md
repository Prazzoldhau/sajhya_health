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
   receptionist, assistant, other) are records without logins.
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
