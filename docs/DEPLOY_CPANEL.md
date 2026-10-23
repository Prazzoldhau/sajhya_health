# Deploying on cPanel (Passenger) - no SSH needed

Host in use: `agni.secureshieldserver.com`, cPanel user `madhyapu`. SSH from outside is closed there, so deployment uses cPanel's browser
**Terminal**: a **plain `git clone`** in your home folder plus `deploy/cpanel_deploy.sh`. Claude (or any developer) only needs to **push to GitHub**;
you run two commands in the Terminal.

> **Lesson from the earlier Dhaubanjar deployment on this same server:** do **not** use cPanel's *Git Version Control* screen, and never keep the app
> inside `~/repositories/`. cPanel creates that folder private (mode `700`), the web server's app process cannot enter it, and the app silently
> never starts (every URL gives a generic 404 and nothing is logged). A plain `git clone` made in the Terminal, with normal folder permissions, works.
> Also, cPanel's *Setup Python App* **overwrites `passenger_wsgi.py` with a template that uses `imp`** whenever the app is created or recreated; the
> deploy script copies our correct file back, so run a deploy after (re)creating the app.

> **Never point this project at the live `madhyapu_sajhya_db`.** It shares Django's own tables (`django_migrations`, `auth_*`, sessions)
> with the old site and would clash. Create a **new database** and, first, deploy to a **test subdomain** (for example `app.sajhya.com`).

## One-time setup (about 30 minutes)

1. **Database** - cPanel > *MySQL Databases*: create a database (e.g. `madhyapu_shealth`) and a new user with a strong password, add the user to
   the database with **All Privileges**. Write down the three names. The URL is `mysql://madhyapu_suser:PASSWORD@localhost:3306/madhyapu_shealth`
   (URL-encode special characters in the password: `@` -> `%40`, `#` -> `%23`).
2. **Subdomain** - cPanel > *Domains/Subdomains*: create `app.sajhya.com` (document root can be anything; Passenger replaces it).
3. **Python app** - cPanel > *Setup Python App* > *Create Application*: Python **3.11** (3.11.17 is what the other apps on this server run; 3.12 also works with our file), **Application root** `sajhya_health`,
   **Application URL** `app.sajhya.com`, **Startup file** `passenger_wsgi.py`, **Entry point** `application`. Create it. (This also creates the
   virtualenv the deploy script finds automatically.)
4. **Settings file** - cPanel > *File Manager* > open `sajhya_health/` (the application root) > create a file named `.env` (copy of `.env.example`) with:
   ```
   DEBUG=False
   SECRET_KEY=<60+ random characters>          # Terminal:  python3 -c "import secrets; print(secrets.token_urlsafe(60))"
   ALLOWED_HOSTS=app.sajhya.com
   CSRF_TRUSTED_ORIGINS=https://app.sajhya.com
   DATABASE_URL=mysql://madhyapu_suser:PASSWORD@localhost:3306/madhyapu_shealth
   BEHIND_PROXY=True
   SECURE_SSL_REDIRECT=True
   SECURE_HSTS_SECONDS=0            # raise to 31536000 only after HTTPS works everywhere
   PRIVATE_MEDIA_ROOT=/home/madhyapu/sajhya_private      # outside the web root; create the folder
   ADMIN_URL=office-7k2/            # pick your own
   EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend  + the EMAIL_* lines from .env.example (use a cPanel mailbox)
   ```
   Turn on a free **AutoSSL** certificate for the subdomain (cPanel > *SSL/TLS Status*).
5. **Source code** - cPanel > *Terminal*:
   ```
   cd ~
   git clone https://github.com/Prazzoldhau/sajhya_health.git sajhya_src
   ls -ld ~/sajhya_src ~/sajhya_health        # both should start with drwxr-xr-x or drwxrwxr-x, NOT drwx------
   ```
   (If the repository is private, Git asks for a username and a personal access token.) `~/sajhya_src` is only the source checkout; the running app is
   the separate `~/sajhya_health` folder created in step 3, and the script copies the code across.
6. **Pictures** - `static/exercises/` is about 750 MB. Either let git carry it (slow but simple) or: add `static/exercises/` to a zip, upload it with
   File Manager to `sajhya_health/static/exercises/` on the server, and exclude it from rsync (`--exclude 'static/exercises/'` in the script).

## Every deployment

1. Claude/you: `git push` to GitHub (tests pass first: `python manage.py test`).
2. cPanel > *Terminal*:
   ```
   cd ~/sajhya_src && git pull
   bash deploy/cpanel_deploy.sh
   ```
3. The script (`deploy/cpanel_deploy.sh`) backs up the database to `~/backups/db_<time>.sql.gz` (keeps 10), copies the code to `~/sajhya_health`
   (never touching `.env`, `media/`, `private_uploads/`, `logs/`; it also restores our `passenger_wsgi.py`), installs requirements, runs `check`, `migrate`,
   `collectstatic`, and restarts the app. The **first** run also loads the reference data (ICD-10, exercises, pharmacy, labs, shop, assessment scales).
4. Open `https://app.sajhya.com/healthz/` - it must answer `{"status": "ok"}`.

If a deploy fails nothing is half-done in the database: the script stops at the first error. Run it by hand to see the message:
cPanel > *Terminal*: `cd ~/sajhya_src && bash deploy/cpanel_deploy.sh`.

## After the first deploy

In the Terminal (activate the app's virtualenv first; the top of *Setup Python App* shows the exact `source .../activate` line):
```
cd ~/sajhya_health
python manage.py createsuperuser        # your staff login; the admin is at the ADMIN_URL you chose
python manage.py check --deploy
```
Then test as a user: sign up a professional, approve it at `/accounts/review/`, add a patient, write a SOAP note, publish a plan, link a patient
account, place a shop order. Add a monthly cron (cPanel > *Cron Jobs*): `0 6 1 * * cd ~/sajhya_health && ~/virtualenv/sajhya_health/3.11/bin/python manage.py clinic_usage`.

## Rolling back

- Code: `cd ~/sajhya_src && git checkout <previous-commit>` (or `git revert` and push, then `git pull`), then `bash deploy/cpanel_deploy.sh` again.
- Data: `gunzip -c ~/backups/db_<time>.sql.gz | mysql -u madhyapu_suser -p madhyapu_shealth` (restores the backup taken just before that deploy).

## Making it fully hands-off (optional)

SSH from outside is blocked, which is why a person clicks *Deploy*. Ask the host to open SSH (give them your public key `claude-deploy`, already
authorised in cPanel) and Claude can run `ssh ... "cd ~/sajhya_src && git pull && bash deploy/cpanel_deploy.sh"` itself. Keep the
approval prompt on for that command.

## Troubleshooting

- *Every URL gives a plain 404 / nothing is logged*: the app folder is not enterable (`ls -ld ~/sajhya_health` must not be `drwx------`; run `chmod 755 ~/sajhya_health`) or it sits under `~/repositories/`. Also `cat ~/sajhya_health/passenger_wsgi.py` - if it contains `imp.load_source` it is cPanel's template: run the deploy script again.
- *"No cPanel Python virtualenv found"*: create the app first (step 3). *"Missing .env"*: step 4 (the file lives in the application root).
- *500 error on the site*: `~/sajhya_health/logs/sajhya.log` has the traceback; also cPanel > *Errors*.
- *Static files/pictures missing*: the deploy ran `collectstatic`? Is `static/exercises/` on the server? Is the subdomain's `/static/` served by Passenger/WhiteNoise (it is, via WhiteNoise)?
- *Changes not visible*: the restart touches `tmp/restart.txt`; or click *Restart* in *Setup Python App*.
- *Database access denied*: the user is not added to the database with privileges, or the password in `DATABASE_URL` is not URL-encoded.
