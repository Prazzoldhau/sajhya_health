# Assessments (outcome measures)

The `assessments` app lets a physiotherapist pick **scales** (Barthel, Berg, FIM, NIHSS, ODI ...) or a ready-made **form**
(a bundle such as "Stroke / neurology - initial"), score them for a patient, and see progress over time. It is separate from
`accounts` on purpose: scales are *data*, so you can add, change or retire them without touching code.

## Where things are

| What | Where |
| --- | --- |
| Patient page tab | Patient -> **Assessments** (progress table + history, **New assessment** button) |
| Choose scales / fill / view a record | `/assessments/patients/<id>/new/`, `.../fill/`, `/assessments/sessions/<id>/` |
| Scales, questions, score bands, forms | Django admin -> **Assessments** |
| Shipped starter set | `assessments/fixtures/scales.json`, loaded by `python manage.py load_scales` |
| Scoring rules | `assessments/scoring.py` (pure functions, unit-tested) |

## What ships (25 scales, 10 forms)

- **Functional/ADL**: Barthel Index, FIM, Modified Rankin
- **Balance/falls**: Berg, Timed Up and Go, Functional Reach, 30-second chair stand
- **Neurology**: NIHSS, Glasgow Coma Scale, Modified Ashworth (tone), MRC muscle grade
- **Coordination**: SARA (ataxia), Nine-Hole Peg Test (right and left)
- **Orthopaedic**: Oswestry (back), Neck Disability Index, Lower Extremity Functional Scale
- **Pain**: Numeric Pain Rating Scale
- **Endurance**: 6-Minute Walk, 10-Metre Walk, Borg RPE, hand grip
- **Paediatric**: GMFCS, Paediatric Balance Scale, gross-motor milestones checklist

Forms: Stroke/neurology initial, Neurology follow-up, Brain injury, Low back pain, Neck pain, Lower limb, Balance and falls risk,
Coordination/ataxia, Paediatric motor, Endurance and walking.

## Important caveats (clinical and legal)

- **Generic anchors**: for Berg, Paediatric Balance, ODI/NDI and SARA the app shows the *general* 0-4 / 0-5 grade descriptions,
  not each item's full published wording (those are long and often copyrighted). The clinician grades against the official
  instrument; the app records and totals the grade. The scale's instructions say so on screen.
- **FIM** is a trademarked instrument owned by Uniform Data System for Medical Rehabilitation. It is included because it was
  requested; **confirm your clinic holds the licence** or deactivate it (untick *Is active* in the admin).
- Score bands (e.g. Berg 41-56 low fall risk) are common published cut-offs. Check them against the version your clinic uses
  and edit them in the admin if needed.
- Everything here supports clinical judgement; it does not diagnose.

## How scoring works

| Scoring | Meaning | Examples |
| --- | --- | --- |
| `sum` | Add up the item values | Barthel, Berg, FIM, NIHSS, GCS, LEFS |
| `percent` | Sum / maximum of the items answered x 100 (items may be optional) | Oswestry, NDI |
| `single` | One item; its value is the score | TUG (seconds), NPRS, mRS, Ashworth, 6MWT |

`higher_is_better` decides whether a change is labelled *Improved* or *Worse*. `mcid` (minimal important change), if set,
stops tiny changes being called improvement ("below the minimal important change"). Bands turn a score into a label such as
"Moderate fall risk".

## Adding a new scale (no code)

Admin -> Assessments -> Assessment scales -> Add.
1. Fill the header: **code** (short, unique, never change it later), name, category, scoring, unit, direction.
2. **Score bands** (optional): min/max/label/tone.
3. **Items**: for each question set order, label, and either
   - *Pick one option*: type options one per line as `score|label`, e.g. `4|Independent`, or
   - *Enter a number*: set min/max.
4. Optionally add it to a **form** (Assessments -> Assessment forms) so it appears in a bundle.

## Changing a scale later

Edit it in the admin. Raise **Version** when the questions or scoring change. Existing patient results are **not rewritten**:
each result stores a snapshot (scale name, version, every question and answer, score, interpretation), so old records always
read as they were recorded. To retire a scale untick **Is active**: it disappears from new assessments but history stays.
Do not change a scale's *code* once results exist (progress tables group by it).

## Adding many scales from a file

Copy the structure of `assessments/fixtures/scales.json`:

```json
{"scales": [{"code": "my-scale", "name": "My Scale", "abbreviation": "MS", "category": "ortho", "scoring": "sum",
             "unit": "points", "higher_is_better": true, "mcid": null, "description": "", "instructions": "", "reference": "",
             "items": [{"code": "q1", "label": "Question 1", "input_type": "choice", "options_text": "2|Good\n1|Fair\n0|Poor", "required": true}],
             "bands": [{"min_score": 0, "max_score": 1, "label": "Poor", "tone": "bad"}]}],
 "forms": [{"name": "My form", "category": "ortho", "description": "", "scales": ["my-scale"]}]}
```

Run `python manage.py load_scales path/to/file.json`. Existing scales are **skipped** (so admin edits survive); add `--update`
to overwrite them with the file's version. Categories: functional, balance, coordination, neuro, ortho, pedia, pain, cardio, other.

## Tips and troubleshooting

- *"No forms yet" on the New assessment page*: run `python manage.py load_scales`.
- *A scale will not save*: a started scale must be fully answered (or leave it completely blank to skip it). Optional items are
  marked "(optional)".
- *Progress shows "First reading"*: a change needs two readings of the same scale.
- Per-muscle or per-side scales (Ashworth, MRC, grip): record one assessment per muscle/side and name it in the scale's notes.
- Access: only the owning professional can open, add or delete a patient's assessments; unapproved professionals are locked out
  like everywhere else.

## Disciplines: who sees which assessment

Every scale, scale form, clinical form and recorded assessment belongs to a **discipline** (physiotherapy, occupational therapy, speech therapy,
behaviour therapy, or general). People see only their own discipline's items plus the general ones, taken from their profession: a physiotherapist
never sees occupational therapy assessments (in the list to choose from, on the patient's Assessments tab, or by opening one), and an
occupational therapist never sees the physiotherapy ones. Someone who is not one specific discipline (the clinic's own login, a doctor) can work in
any, and switches between them with the chips at the top of *New assessment*; their history shows a label saying which discipline each belongs to.
Everything that existed before is physiotherapy. To share a scale with every discipline, set its *Discipline* to General in the admin
(Assessments, Assessment scales).

## Clinical forms (history and examination forms)

Some assessments are not scored scales but a long form of text boxes, tick boxes and tables. These are **clinical forms** (`ClinicalForm`), filled
once per patient and kept as a **ClinicalRecord** with a copy of the questions it was filled with.

- **Shipped:** *Paediatric occupational therapy assessment* (`ot-pediatric`, occupational therapy): demographic data; pre-natal, peri-natal and post-natal
  history; medical, family, educational and socio-economic history; motor and oral-motor development; observation and examination; gross and fine
  motor skills and in-hand manipulation; proximal senses (vestibular, proprioceptive, gravitational, tactile, dyspraxia); distal senses (vision, visual
  perception, auditory, olfactory, gustatory, reflexes); activities of daily living; pre-handwriting skills; behaviour; play; problem identification,
  short and long term goals, approaches and techniques. Name, age, gender and diagnosis are filled from the patient record.
- **Where:** patient, *Assessments*, *New assessment*, *Clinical assessment forms*. A saved form opens read-only (only what was answered is shown) and prints.
- **Adding or changing one:** the questions are data in `assessments/clinical_forms.py` (field types are described at the top of that file).
  `python manage.py migrate` adds new forms; `python manage.py load_clinical_forms` brings a changed form up to date and raises its version.
  Records already filled keep the questions they were filled with.
