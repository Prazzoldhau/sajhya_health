# Patient dashboard and portal ("My dashboard")

Every free **Client** account gets a patient dashboard at `/portal/`. It is a web app layout: a **vertical menu on the left**
(Home, Treatment plan, My exercises, Do's & don'ts, Shop & services, Settings) and a wide content area; on phones and tablets
the menu becomes a swipeable bar across the top. Code: the `portal` app.

## What a patient can do

| Page | URL | Content |
| --- | --- | --- |
| Home | `/portal/` | greeting; if a record is linked: next appointment, exercise progress, plan summary; always: the three service tiles |
| Treatment plan | `/portal/plan/` | the **published (active)** plan: goals, progress (start / now / goal), phases with clinic and home items - in two columns on wide screens |
| My exercises | `/portal/exercises/` | the **active** prescription: picture, dose, rest, time of day; *How to do it* (description, step images, video); **Mark as done**; **How did it feel?** |
| Do's & don'ts | `/portal/advice/` | **Do** = the plan's *Patient education* text; **Don't** = its *Precautions* text; plus a fixed safety note |
| Shop & services | `/portal/services/` | cards for **Pharmacy**, **Marketplace** and **Lab investigations** (they open the existing public pages, which show a "My dashboard" link back for signed-in clients) |
| My orders | `/portal/orders/` | pharmacy and marketplace orders placed from the account, with live status, items, total and a link to the confirmation |
| My lab bookings | `/portal/lab/` | lab bookings made from the account, with tests, status and total |
| Settings | `/portal/settings/` | **link a treatment record**, linked records (open / unlink), email, change password |

A client with nothing linked still has a useful dashboard (services); the treatment pages tell them to link a record in Settings.
Signing in as a Client always lands on this dashboard.

## How a patient links their treatment record (decision)

The link lives in **Settings -> Link a treatment record**. A patient uses an ordinary **free Client account** and links it to
their record with a **one-time code** from their physiotherapist **plus their date of birth**. They do **not** sign in with the
patient code (`PAT-2026...`): it is printed on paperwork and is easy to guess, so on its own it would let a stranger read
someone's treatment.

1. **Physio**: open the patient -> Overview -> **Patient portal** -> *Create patient portal code* (the patient needs a date of
   birth on file). A page shows a code like `K7M2-9QXA` with printable instructions. The code is stored scrambled (hashed), so it
   is shown **once**; if lost, create a new one (the old one stops). It works once and expires after **7 days**.
2. **Patient**: creates a free **Client** account (or signs in), opens **Settings**, enters the code and their date of birth.
   The dashboard then fills with their plan, exercises and advice.

Safeguards: a wrong birth date against a known code counts against that code (5 strikes and the code dies); each account is
paused for 15 minutes after 6 wrong attempts; every failure shows the same vague message; one patient record can have only one
portal account (remove access first to re-link); a used or expired code is dead. A parent can link several children to one
account (a "Viewing" selector appears in the menu). Either side can end it: the patient with *Unlink*, the physio with *Remove
access* (patient Overview tab).

## What the patient never sees

Draft plans, old/cancelled prescriptions, SOAP notes, clinician notes, billing, visit notes, assessments, phone/email/address,
other patients. So write the plan's education and precautions in plain language the patient can follow.

## What the physio gets back

Exercise ticks update the prescription's progress; each *How did it feel?* answer appears under the exercise on the patient's
**Exercises** tab (red for *painful* / *increased symptom*).

## Notes and limits

- No SMS / email is sent (no gateway yet): the physio hands over the code. When messaging exists, send the code with it.
- Ticking is per exercise (not per day); a daily adherence log would need a new model.
- The dashboard is responsive (desktop sidebar layout, swipeable top menu on small screens) and uses no JavaScript.
- **Orders and lab bookings are tied to the account** (`Order.user`, `LabTestRequest.user`). Staff change a status in the admin and the
  patient sees it on their dashboard from any device. Checkout and lab-booking forms are pre-filled from the account and its latest
  order. Guests can still order without an account.
- **Guest orders become the account's** in two safe ways: (1) automatically when the same browser then signs in or signs up (the
  browser already proved it placed them); (2) manually under *Placed one before you had an account?* on My orders / My lab bookings
  with the **order number plus the email it was placed with** (6 wrong tries pauses it for 15 minutes; a claimed order cannot be
  taken by anyone else). Matching by email alone is deliberately not done: emails are not verified, so anyone could claim
  someone else's orders.
- Orders placed before this feature, as a guest, stay unlinked until claimed. The confirmation pages show guests a "create a free
  account to track this" note.
- Future: lab *results* can now be attached to a booking and shown only to its owner; order history is ready for reorder buttons.
- Clinic patients: any physio who can open the patient can create a code; contact details stay hidden from physios as before.

## Troubleshooting

- *"Do not match, or the code has expired"*: wrong code or birth date, expired (7 days), already used, or too many tries - create a new code.
- *"Too many wrong attempts"*: wait 15 minutes (the pause is per account).
- *Where do I link a record?* Settings in the dashboard menu (`/portal/settings/`).
- *Cannot create a code*: the patient has no date of birth, or already has a portal account (Remove access first).
- *Patient sees nothing under Plan/Exercises*: the plan is still a draft, or no active prescription exists.
- Admin: Portal -> Patient links / Portal invites show who is linked and the invites (the code itself is never stored).
