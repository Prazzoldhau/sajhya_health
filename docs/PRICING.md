# Pricing rules and how to run them

There is **no online payment yet**: money is collected by staff, then recorded in the admin. The rules below are enforced by the
software; the numbers are settings (`.env`) and can be overridden per professional / clinic in the admin.

## Client (patient) - free

Free forever: dashboard, pharmacy / marketplace / lab booking, treatment portal.

## Professional - first 10 patients free, then NPR 200 per patient

- A professional may register **10 patients free**. The 11th needs a **patient slot**.
- A slot is one extra patient, **NPR 200**, paid once. The professional orders slots in **Settings -> Plan & usage**
  (how many, cost shown), staff collect the money and **mark the order paid** in the admin: Billing -> **Slot orders** -> select ->
  action *Mark paid and add the slots*. The slots are added once (marking twice does nothing).
- At the limit, *Add patient* sends them to Plan & usage with a message; a banner on the Patients page warns from the last 3 slots.
- Patients registered **inside a clinic** are not counted (the clinic plan covers them). Patients that move to a clinic owner when a
  physio leaves are also exempt.
- Admin: Billing -> **Patient allowances** shows/edits each professional's free limit, paid slots and rate (a special deal, or a
  comped batch of slots).
- **Existing professionals** who already had more than 10 patients when this started were given matching pre-paid slots, so
  nothing broke; they must buy slots to add more.
- Settings: `FREE_PATIENT_LIMIT=10`, `PATIENT_SLOT_RATE=200`.

## Clinic - 400 new patients per month included, NPR 200 for each extra

- The clinic plan itself is activated by staff (see CLINICS.md). A clinic may **enrol 400 new patients per calendar month**
  (Nepal time) - "enrol" = a patient record registered inside the clinic that month.
- Going over is **never blocked**: each patient above the cap is added as a **due** (NPR 200 each) to be paid **before the
  clinic's next billing**.
- Where to see it: the clinic **Overview** shows "New patients enrolled this month: N of 400" with a meter, the overage and a table of
  the last 6 months (owner only: amounts and status). The team sees the count, not the money.
- Staff: admin -> Clinics -> **Clinic monthly usage**: filter *Due*, collect, action **Mark as paid** (freezes that month).
  Run `python manage.py clinic_usage` on the 1st (cron) to prepare the dues; it lists clinics that owe money.
- Override per clinic owner in Clinics -> Clinic subscriptions: *Monthly patient cap* and *Overage rate*.
- Settings: `CLINIC_MONTHLY_PATIENT_CAP=400`, `CLINIC_OVERAGE_RATE=200`.
- Notes: rows for past months stay *Due* until paid (they never disappear from the total); a paid month is frozen even if patients are
  later changed. If staff delete a patient in the admin the count falls (counts are live until paid).

## Plan page

The Professional card reads "Free - First 10 patients free, then NPR 200 per patient" (Billing -> Plans -> *Price note* and features
are editable text).

## Troubleshooting

- *"You have used all N patient slots"*: buy slots (Plan & usage). Staff: mark the order paid.
- *Slots not added after marking paid*: use the *Mark paid* **action** (it adds the slots); editing the status field by hand does not.
- *Clinic dues look wrong*: open the month in Clinic monthly usage; numbers are recomputed from patient records until marked paid.
