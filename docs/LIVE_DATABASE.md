# Live database (sajhya.com) and this project

On 2026-10-22 a real export of the live site (`madhyapu_sajhya_db`, MariaDB, **85 tables**, 54 MB) was compared with this
project. The goal: **every live table and column has a home here**, so that live data can be loaded later without breaking anything.

> The export contains **real patient data, password hashes and sessions**. It is *not* in the repository (`*.sql` is git-ignored).
> Keep it private; only its structure (no data) is committed as `extras/live_schema.json`.

## Result

| | Tables |
| --- | --- |
| Already had a matching model here (columns checked, a few added) | 33 |
| **Added in this step** (new app `extras`, 40 models + 3 many-to-many links) | 43 |
| Django internals (not carried over) | 9 |

`python manage.py audit_live_dump` (default: the committed structure file, or pass a new `.sql` export) re-checks all of it - **671 columns,
0 unmapped**. It is also a test, so the map cannot rot. If the live site gets a new table/column, export again and run it: it names the gap.

## What was added to existing tables (columns the live site had that this project did not)

| Table / model | New column(s) | Why |
| --- | --- | --- |
| `accounts.Patient` | `qr_code`, `qr_token`, `legacy_username`, `legacy_password_hash`, `activation_expires_at`, `enterprise` | the old patient app (QR pairing, patient login, enterprise origin); the old password hash is kept but never shown, new sign-in is the portal code flow |
| `accounts.Account` | `personal_code`, `pairing_token` | physio codes used to pair patients |
| `billing.PackagePayment` | `recorded_by` | who took the payment |
| `lab.LabTestRequest` | `patient` | bookings made for a patient record |
| `marketplace.OrderItem` | `lab_test`, `lab_panel` | the shop could sell lab items |
| `exercises.Prescription` | `prescription_date` | printed prescription date |
| `exercises.PrescriptionExercise` | `library_exercise_id`, `created_at`, `updated_at` | the old numeric library reference and timestamps |
| `profiles.PatientProfile` | `nursing_vitals` | free-text vitals note |

## Columns deliberately **not** carried over

`clinic.updated_at`; `addpatient.completed_session` (derived from visits here); `addpatient.is_deleted` / `deleted_at` (soft-deleted patients are not
imported); `addpatient.diagnosis_code` and the `diagnosiscode` table (empty live; this project loads the full WHO ICD-10 list); Django's own
tables (sessions: 50,406 rows, admin log: 3,617 rows - not worth carrying).

## Tables that map onto models this project already had

| Live table | Rows | Here |
| --- | --- | --- |
| `account_app_user` | 10 | `auth.User` |
| `assessment_app_patientscaleassessment` | 1 | `assessments.AssessmentResult` |
| `billing_app_billingentry` | 0 | `billing.BillingEntry` |
| `billing_app_packagepayment` | 3 | `billing.PackagePayment` |
| `billing_app_patientpackage` | 2 | `billing.PatientPackage` |
| `clinic_account_clinic` | 3 | `clinics.Clinic` |
| `clinic_account_clinicphysio` | 2 | `clinics.ClinicMember` |
| `clinic_account_queueentry` | 5 | `clinics.QueueEntry` |
| `exercise_app_exercisemain` | 790 | `exercises.ExerciseMain` |
| `exercise_app_exercisestepimage` | 1,928 | `exercises.ExerciseStepImage` |
| `exercise_app_region` | 5 | `exercises.Region` |
| `exercise_app_subregion` | 30 | `exercises.SubRegion` |
| `exercise_feedback` | 37 | `exercises.ExerciseFeedback` |
| `lab_app_labtest` | 91 | `lab.LabTest` |
| `lab_app_labtestpanel` | 10 | `lab.LabTestPanel` |
| `lab_app_labtestpanel_tests` | 43 | `lab.LabTestPanel.tests` |
| `lab_app_labtestrequest` | 3 | `lab.LabTestRequest` |
| `lab_app_labtestrequestitem` | 11 | `lab.LabTestRequestItem` |
| `marketplace_app_category` | 39 | `marketplace.Category` |
| `marketplace_app_order` | 11 | `marketplace.Order` |
| `marketplace_app_orderitem` | 14 | `marketplace.OrderItem` |
| `marketplace_app_pharmacyproduct` | 25 | `marketplace.PharmacyProduct` |
| `marketplace_app_product` | 995 | `marketplace.Product` |
| `marketplace_app_productimage` | 0 | `marketplace.ProductImage` |
| `marketplace_app_productvariant` | 287 | `marketplace.ProductVariant` |
| `personal_account_addpatient` | 85 | `accounts.Patient` |
| `personal_account_diagnosiscode` | 0 | `accounts.Icd10Code` |
| `personal_account_patientaid` | 10 | `profiles.AidEntry` |
| `personal_account_patientbloodtest` | 8 | `profiles.LabEntry` |
| `personal_account_patientmedicalprofile` | 8 | `profiles.PatientProfile` |
| `personal_account_patientmedication` | 46 | `profiles.MedicineEntry` |
| `prescription_exercises` | 1,222 | `exercises.PrescriptionExercise` |
| `prescriptions` | 106 | `exercises.Prescription` |

Renames to know about (the loader must apply them): `patient_name`->`name`, `patient_contact`->`phone`, `patient_diagnosis`->`diagnosis`, `created_by`/`physio`->`professional`
(a live *user* becomes its `ProfessionalProfile`), `origin_clinic`->`clinic`, `clinic_name`->`name`, `clinic_code`->`code`, `time_of_day` (medication)->`morning/afternoon/evening/night`,
`user_type`->`Account.account_type`, `license_verified`->`ProfessionalProfile.status` (verified = approved), `scale/items/total_score` (assessments)->`AssessmentResult`.
The full column-level map is `extras/live_map.py`.

## Tables added in the `extras` app (live features with no screens here yet)

The models mirror the live columns exactly (names, lengths, nullability, unique keys); they are registered in the admin so staff can read and
correct the data. Building screens for them is future work and is independent of the data model.

| Live table | Rows | Model |
| --- | --- | --- |
| `assessment_app_regionalassessment` | 0 | `extras.RegionalAssessment` |
| `assessment_app_specialtestreference` | 27 | `extras.SpecialTestReference` |
| `careers_app_vacancy` | 3 | `extras.CareerVacancy` |
| `careers_app_vacancyapplication` | 4 | `extras.CareerApplication` |
| `delivery_app_delivery` | 0 | `extras.Delivery` |
| `delivery_app_rider` | 0 | `extras.DeliveryRider` |
| `delivery_app_zone` | 7 | `extras.DeliveryZone` |
| `donate_app_donatablecategory` | 14 | `extras.DonatableCategory` |
| `donate_app_donationpledge` | 1 | `extras.DonationPledge` |
| `donate_app_donationpledge_items` | 4 | `extras.DonationPledge.items` |
| `enterprise_account_enterprise` | 2 | `extras.Enterprise` |
| `enterprise_account_enterprisestaff` | 0 | `extras.EnterpriseStaff` |
| `enterprise_account_physiorequest` | 10 | `extras.PhysioRequest` |
| `enterprise_account_ward` | 5 | `extras.EnterpriseWard` |
| `find_physio_app_bookingrequest` | 3 | `extras.BookingRequest` |
| `find_physio_app_physioavailability` | 2 | `extras.PhysioAvailability` |
| `find_physio_app_physioprofile` | 10 | `extras.PhysioListing` |
| `find_physio_app_physioprofile_specializations` | 0 | `extras.PhysioListing.specializations` |
| `find_physio_app_physioreview` | 0 | `extras.PhysioReview` |
| `find_physio_app_specialization` | 0 | `extras.Specialization` |
| `marketplace_app_commission` | 2 | `extras.Commission` |
| `marketplace_app_commissionrate` | 0 | `extras.CommissionRate` |
| `marketplace_app_diagnosisproductmap` | 0 | `extras.DiagnosisProductMap` |
| `marketplace_app_diagnosisproductmap_products` | 0 | `extras.DiagnosisProductMap.products` |
| `marketplace_app_patientproductrecommendation` | 2 | `extras.ProductRecommendation` |
| `patient_app_appopenevent` | 68 | `extras.AppOpenEvent` |
| `patient_app_pushsubscription` | 0 | `extras.PushSubscription` |
| `patient_app_videoclickevent` | 241 | `extras.VideoClickEvent` |
| `personal_account_activationcard` | 50 | `extras.ActivationCard` |
| `personal_account_patientassessmententry` | 1 | `extras.PatientTestEntry` |
| `personal_account_patientconsultation` | 0 | `extras.PatientConsultation` |
| `personal_account_patientdietentry` | 0 | `extras.PatientDietEntry` |
| `personal_account_patientexercise` | 5 | `extras.PatientSavedExercise` |
| `personal_account_patientphysiopairing` | 65 | `extras.PatientPhysioPairing` |
| `personal_account_rx` | 0 | `extras.MedicineRx` |
| `prescription_app_modality` | 13 | `extras.TreatmentModality` |
| `prescription_app_treatmentsession` | 42 | `extras.TreatmentSession` |
| `prescription_app_treatmentsessionmodality` | 58 | `extras.TreatmentSessionModality` |
| `referral_app_referral` | 0 | `extras.Referral` |
| `summit_app_sessionsubmission` | 13 | `extras.SummitSession` |
| `summit_app_table` | 6 | `extras.SummitTable` |
| `upload_app_apkrelease` | 11 | `extras.ApkRelease` |
| `visit_notes_app_visitnote` | 20 | `extras.VisitNote` |

Groups: **patient app** (activation cards, QR/physio pairing, app-open and video-click analytics, push subscriptions), **clinical** (regional
assessments, special-test reference, treatment sessions with modalities, the detailed 70-field visit note, consultations, diet entries, saved
exercises, medicine prescriptions, referrals), **directory** (public physio listings, availability, booking requests, reviews, specialisations),
**enterprise** (hospitals, staff, wards, ward physio requests), **shop extras** (commissions, commission rates, diagnosis->product map,
product recommendations), **delivery** (zones, riders, deliveries), **site** (careers, donations, summit sessions, Android app releases).

## Django internals not carried over

| Live table | Rows | Note |
| --- | --- | --- |
| `account_app_user_groups` | 0 | Django internals: no groups were used (0 rows) |
| `account_app_user_user_permissions` | 0 | Django internals: no per-user permissions were used (0 rows) |
| `auth_group` | 0 | Django internals: Django permissions are re-created by migrate |
| `auth_group_permissions` | 0 | Django internals: same |
| `auth_permission` | 316 | Django internals: same |
| `django_admin_log` | 3,617 | Django internals: admin history of the old site (3,600 rows) is not carried over |
| `django_content_type` | 79 | Django internals: rebuilt by migrate |
| `django_migrations` | 135 | Django internals: the old site's migration history |
| `django_session` | 50,406 | Django internals: login sessions (50,000 rows) expire; users sign in again |

## Loading the live data later (not done yet)

The structure is ready; **importing the rows is a separate, deliberate step** because it moves real people's data and passwords:
1. Work on a **copy** of this project's database, never production first.
2. Users: live passwords are Django hashes, so they stay valid. Create `auth.User` + `Account` (+ `ProfessionalProfile` for physios, status from `license_verified`).
3. Then clinics, patients (skip `is_deleted`), prescriptions/exercises, billing, labs, shop orders, profile entries, and the `extras` tables.
4. Keep an id-mapping (live id -> new id) per table; apply the renames above; re-run `python manage.py audit_live_dump` and the test suite.
5. Reference catalogues (exercises, shop products, labs) were already loaded from the old project's fixtures; compare before overwriting.
If you want, the loader can be written next as `manage.py import_live_dump <dump.sql> --dry-run` with a report before anything is saved.

## Troubleshooting

- *`audit_live_dump` reports UNMAPPED*: the live site changed. Add the field/model (or a mapping in `extras/live_map.py`) and migrate.
- *Where is X from the live site?* search this page or `extras/live_map.py` for the live table name.
- *Never commit a `.sql` dump*: it holds patient data (the repository ignores `*.sql`).
