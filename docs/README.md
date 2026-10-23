# Sajhya Health - documentation

Start here. Everything a person needs to run, understand, fix and extend the project without asking anyone.

| Read this | When |
| --- | --- |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Something is broken or behaves oddly. Organised by what you *see*, with the cause and the fix. |
| [OPERATIONS.md](OPERATIONS.md) | Deploying, updating, backing up, restoring, managing users, reading logs. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | You want to understand how it fits together, or add a feature. Includes recipes. |
| [ASSESSMENTS.md](ASSESSMENTS.md) | Using, adding or changing assessment scales and forms (Barthel, Berg, FIM ...). |
| [DEPLOY_CPANEL.md](DEPLOY_CPANEL.md) | Deploying on cPanel/Passenger without SSH (Terminal + plain git clone): database, Python app, `.env`, deploy script, rollback, lessons from the Dhaubanjar deployment. |
| [LIVE_DATABASE.md](LIVE_DATABASE.md) | How the live sajhya.com database maps onto this project (every table/column), what was added, how to audit and later load it. |
| [PRICING.md](PRICING.md) | Pricing rules (professional 10 free + NPR 200 per patient, clinic 400/month cap) and how staff run them. |
| [QA_REPORT.md](QA_REPORT.md) | What was tested before deployment, bugs found, remaining risks, how to repeat. |
| [PORTAL.md](PORTAL.md) | The patient dashboard: services, linking a treatment record, what patients see, safeguards. |
| [SOAP_NOTES.md](SOAP_NOTES.md) | The SOAP note form, locking/addenda, and how a treatment plan starts from a note. |
| [CLINICS.md](CLINICS.md) | The Clinic plan, team invitations, queue, privacy rules and how staff activate a clinic upgrade. |
| [DECISIONS.md](DECISIONS.md) | You wonder *why* something was built a certain way, or what is unfinished. |
| [../README.md](../README.md) | Quick setup and the production checklist. |

## The 60-second picture

- **Django 5.2 + MySQL**, server-rendered pages with a little JavaScript. No front-end build step.
- Apps: `accounts` (users, onboarding, patients, appointments, treatment plans), `billing` (daily book, patient packages,
  account plans), `exercises` (library + prescriptions), `profiles` (patient medicine / nursing / aids / rehab / lab), `assessments` (outcome-measure scales, forms and results), `clinics` (clinic plan, team, queue), `soapnotes` (SOAP notes), `portal` (patient view),
  `marketplace` (shop + pharmacy), `lab` (public lab-test booking), and the project package `sajhya_health`.
- **Who can see what** is decided in one file: `accounts/access.py`. A professional only ever sees their own patients.
- **Tests**: `python manage.py test` (346 tests, ~12 s). `sajhya_health/test_end_to_end.py` walks the whole product; if it
  fails, start there.
- **When something is wrong in production**: look at `/healthz/`, then the log (`logs/sajhya.log`), then
  [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
