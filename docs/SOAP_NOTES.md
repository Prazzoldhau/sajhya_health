# SOAP notes

A physiotherapy SOAP note (Subjective, Objective, Assessment, Plan) for each patient, for when no standard scale fits - and
the source a **treatment plan can start from**. Code: the `soapnotes` app.

## Where it is

Patient page -> **SOAP Notes** tab (right after Overview; also *New SOAP Note* in the overview's quick actions).
Pages: `/soapnotes/patients/<id>/new/`, `/soapnotes/<id>/` (read / print), `/soapnotes/<id>/edit/` (drafts only).

## The form (physiotherapy-specific)

- **S - Subjective**: chief complaint, onset/mechanism, pain (now / best / worst 0-10, location, character), history,
  aggravating and easing factors, 24-hour pattern, **red-flag screen** (12 ticks: night pain, weight loss, bladder/bowel
  change, saddle numbness, ...), medical history and medications, functional limitations, patient goals.
- **O - Objective**: observation/posture, palpation, vitals, **range of motion** table (movement, side, active, passive, pain,
  note), **manual muscle test** table (muscle, side, grade 0-5 incl. 3+, 4-, 4+), neurological screen, **special tests**
  (positive / negative / inconclusive), gait/balance/function. Movement, muscle and test names have suggestion lists; free text
  is always allowed.
- **A - Assessment**: clinical impression, **ICD-10 code** (lookup), stage (acute / sub-acute / chronic / post-op), irritability,
  prognosis, problem list, contributing factors.
- **P - Plan**: treatment given today, **baseline metrics** (measure, unit, baseline, target) and **clinical goals** (short/long
  term, target date) *in the same format as the treatment plan builder*, sessions per week and weeks, next review, home
  exercise programme, education, precautions, referral. Optional tick: **also record this as a visit** (once; uses a package
  session like any visit).

## Draft, final and addenda

A note starts as a **draft** (editable and deletable by its author only). **Finalise** locks it. A final note can only be
extended with **dated addenda** (author and time stamped), so what was recorded on the day is never silently rewritten. Final
notes cannot be deleted from the app. Clinic colleagues (see CLINICS.md) can read a shared patient's notes, write their own and
add addenda; only the author edits a draft. The note date cannot be in the future.

## Follow-ups and the treatment plan

- A new note after an earlier one is a **follow-up**: the earlier note's metrics (baseline emptied, so you enter today's
  readings next to the targets) and goals are carried over.
- **Treatment plan**: opening *New treatment plan* automatically **starts from the latest SOAP note that has metrics or goals**
  (a banner says so, with *Start blank instead*). It pre-fills diagnosis and ICD-10, baseline metrics, goals, sessions per week
  and duration of the first phase, precautions and education - all editable. From a note's own page, *Create treatment plan
  from this note* uses that exact note (`?from_soap=<id>`); `?from_soap=none` starts blank. Patients with no notes behave as before.

## For developers

- Everything is validated in `soapnotes/clean.py` (pure functions, unit-tested through the views): dropdown values are
  re-checked, numbers parsed, lists capped, free text length-limited.
- Dynamic tables (ROM, strength, tests, metrics, goals) are edited in JS and posted as JSON strings (`rom_json`, ...).
- Suggestion lists live in `soapnotes/presets.py`; add movements, muscles or tests there.
- Metrics/goals JSON shape: `{name, unit, baseline, target}` and `{text, term: short|long, target_date}` (same as `plans._state`).
- Possible next steps: a progress chart of metrics across notes; copying the previous note's findings forward.

## Troubleshooting

- *Cannot finalise*: a note needs at least a complaint, history, observation, impression or treatment.
- *Edit link gives 404*: only the author can edit a draft; finalised notes are locked (add an addendum).
- *Plan did not pre-fill*: no SOAP note with metrics/goals exists for that patient, or `?from_soap=none` was used.
