# Privacy and security controls

What the platform does to limit and record what its own operator and staff can see, and to harden sign-in. Written for clinics who ask "can you read our data?", and for the person who runs the service.

## The honest limit

Anyone who holds the server and database passwords, and who can deploy code, can read everything and can change any control in this file. The controls below stop accidents, ordinary misuse and curiosity, and they leave evidence. They are **not** a lock against the operator. A clinic that needs protection even against the operator needs a clinic-controlled copy (its own server and database, updates deployed by the clinic) or a second person who controls deployment and the server password.

## What is in place

| Control | How it works |
|---|---|
| **Patient records are not in the Django admin** | `sajhya_health/privacy.py` unregisters every model that holds patient identity or clinical data (patients, visits, SOAP notes, bills, packages, prescriptions, assessments, lab entries, queue, plans, portal links, the patient models of the extras app). The operator keeps accounts, clinics, plans, the exercise library, price lists and the orders staff must process. `ADMIN_SHOW_PATIENT_DATA=True` puts them back: a deliberate bypass for a rare repair, visible in `.env`. |
| **Code-only support view** | `/support/` (staff only): workspaces, patient **codes**, counts, bill numbers and amounts. Never a name, phone number, address or note text. |
| **Access log** | `accounts.AccessLog`, written by the app whenever a patient's record is opened, a PDF downloaded, an export made, something shared with a patient, someone signs in, or platform staff open an admin or support page. The clinic owner reads it at **Settings, Access log** (`/accounts/access-log/`), with platform staff lines marked "Sajhya staff". |
| **Owner is told about support access** | Opening a workspace in the support view e-mails the owner (once per ten minutes) and writes a log line. |
| **Staff sign-in alerts** | A platform staff sign-in, a failed one, and a lockout are e-mailed to `SECURITY_ALERT_EMAILS`. |
| **Two-step sign-in** | Authenticator app codes (RFC 6238, no extra package), ten one-time recovery codes kept as hashes, a used code cannot be reused, five wrong codes end the attempt and ten in 15 minutes lock the second step. Optional for everyone at **Settings, Two-step sign-in**. **Required for platform staff** to open the admin and `/support/` (`REQUIRE_STAFF_MFA`, on by default). |
| **Idle sign-out** | Signed-in people are signed out after `IDLE_LOGOUT_MINUTES` (default 30) without a request. |
| **Browser protections** | A Content-Security-Policy: the safe part is enforced (no framing, no plugins, no `<base>` tricks, forms post only to this site); the strict part (own scripts, styles, images, Google Fonts, YouTube) is Report-Only and reports to `/csp-report/` (written to the log) until the pages no longer need inline scripts. Permissions-Policy turns off camera, microphone, location. |
| **Safe redirects** | "next" and "back" addresses go through `sajhya_health/safe.py`: only a path on this same site is followed. |
| **Sign-up does not confirm which e-mail is registered** | The message says the address "cannot be used to create an account". (A user name can still be reported as taken; fully hiding both needs an e-mail confirmation step.) |

## Settings (in `.env`)

| Setting | Default | Meaning |
|---|---|---|
| `SECURITY_ALERT_EMAILS` | empty | Comma-separated addresses told of staff sign-ins, failures and lockouts. |
| `REQUIRE_STAFF_MFA` | on | Staff need two-step sign-in for the admin and `/support/`. Set to `False` only to recover from a lost phone. |
| `ADMIN_SHOW_PATIENT_DATA` | off | Shows patient records in the admin again. Avoid. |
| `IDLE_LOGOUT_MINUTES` | 30 | 0 turns idle sign-out off. |
| `CSP_ENABLED` | on | Turns the Content-Security-Policy headers off if a page breaks. |
| `ADMIN_URL` | admin/ | Keep it non-obvious on the live site. |

## First deploy: do this in order

1. `git pull`, `python manage.py migrate` (accounts 0031 adds the access log and two-step tables), `touch tmp/restart.txt`.
2. Sign in to the admin: you are taken to **Two-step sign-in**. Install an authenticator app, add the key, enter the code, and **save the ten recovery codes somewhere safe, away from the server**.
3. Put `SECURITY_ALERT_EMAILS=you@example.com` in `.env` and restart.
4. Open **Settings, Access log** as a clinic owner to check it records.
5. Watch the browser console (or `logs/sajhya.log`) for "CSP would block" lines for a week before switching the strict policy on.

## Not covered by the app

Server and database access, hosting configuration, backups (see OPERATIONS.md), the security review by an independent auditor, the written privacy policy, patient consent text and the data processing agreement with each clinic.
