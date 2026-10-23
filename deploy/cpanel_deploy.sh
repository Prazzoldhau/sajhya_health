#!/bin/bash
# Deploy Sajhya Health on a cPanel (Passenger) host. Safe to run again and again.
#   - copies the code from this git checkout to the app folder (never touching .env, media, private_uploads, logs, cache)
#   - backs up the MySQL database first
#   - installs requirements, runs migrations, collects static files, restarts the app
# Run it from a PLAIN git clone (not the cPanel "Git Version Control" folder): cd ~/sajhya_src && git pull && bash deploy/cpanel_deploy.sh
# Settings (override by exporting before running):  APP_DIR (default ~/sajhya_health)   LOAD_CATALOGS=1 (force the one-time data load)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${APP_DIR:-$HOME/sajhya_health}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# The Python of the cPanel "Setup Python App" virtualenv (e.g. ~/virtualenv/sajhya_health/3.11/bin/python)
# cPanel names the virtualenv after the app's "Application root" folder. NEVER pick another app's virtualenv: pip would change that site's packages.
APP_NAME="$(basename "$APP_DIR")"
PY="${PY:-$(ls -d "$HOME/virtualenv/$APP_NAME"/*/bin/python 2>/dev/null | sort -V | tail -1 || true)}"
[ -n "$PY" ] && [ -x "$PY" ] || die "No Python virtualenv for the app '$APP_NAME' (looked in ~/virtualenv/$APP_NAME/). Create the app in cPanel > Setup Python App with Application root '$APP_NAME' first (see docs/DEPLOY_CPANEL.md)."
case "$PY" in "$HOME/virtualenv/$APP_NAME/"*) ;; *) die "Refusing to use $PY: it does not belong to the app '$APP_NAME'.";; esac
case "$APP_DIR" in */repositories/*) die "APP_DIR must not be inside ~/repositories: cPanel makes that folder private (mode 700) and the web server then cannot start the app.";; esac
mkdir -p "$APP_DIR" "$BACKUP_DIR"
chmod 755 "$APP_DIR"   # the web server's app process must be able to enter this folder
[ -f "$APP_DIR/.env" ] || die "Missing $APP_DIR/.env - copy .env.example there and fill in the production values first."

say "Python: $PY ($($PY --version 2>&1))   app folder: $APP_DIR"

# ---- 0. pre-flight: settings, database login, folders, virtualenv. Stops here with a plain explanation if anything is wrong.
say "Checking the server (deploy_doctor)"
cd "$APP_DIR" && "$PY" manage.py deploy_doctor || die "The server is not ready: fix the FAIL lines above, then run this again."

# ---- 1. backup the database (skipped with a warning if it is not MySQL or mysqldump is missing)
say "Backing up the database"
eval "$($PY - "$APP_DIR/.env" <<'PYEOF'
import sys, urllib.parse
url = ''
for line in open(sys.argv[1], encoding='utf-8'):
    if line.startswith('DATABASE_URL='):
        url = line.split('=', 1)[1].strip().strip('"\'')
u = urllib.parse.urlparse(url)
if u.scheme.startswith('mysql'):
    q = lambda v: "'" + (v or '').replace("'", "'\''") + "'"
    print(f"DB_NAME={q(u.path.lstrip('/'))}; DB_USER={q(urllib.parse.unquote(u.username or ''))}; DB_PASS={q(urllib.parse.unquote(u.password or ''))}; DB_HOST={q(u.hostname or 'localhost')}; DB_PORT={q(str(u.port or 3306))}; DB_KIND=mysql")
else:
    print("DB_KIND=other")
PYEOF
)"
if [ "${DB_KIND:-other}" = mysql ] && command -v mysqldump >/dev/null 2>&1; then
    MYSQL_PWD="$DB_PASS" mysqldump --single-transaction --no-tablespaces -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_DIR/db_$STAMP.sql.gz" \
        || die "Database backup failed - not deploying."
    echo "saved $BACKUP_DIR/db_$STAMP.sql.gz"
    ls -1t "$BACKUP_DIR"/db_*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm -f   # keep the 10 newest
else
    echo "WARNING: no MySQL backup made (not a MySQL DATABASE_URL, or mysqldump not available)."
fi

# ---- 2. copy the code (the server-only files are never touched)
if [ "$REPO_DIR" = "$APP_DIR" ]; then
    say "The git checkout is the app folder itself: nothing to copy"
else
    say "Copying code to $APP_DIR"
    rsync -a --delete-after \
        --exclude '.git/' --exclude '.cpanel.yml' --exclude '.env' --exclude 'venv/' --exclude '__pycache__/' \
        --exclude 'media/' --exclude 'private_uploads/' --exclude 'logs/' --exclude 'cache/' --exclude 'tmp/' --exclude 'staticfiles/' \
        "$REPO_DIR/" "$APP_DIR/"
fi

cd "$APP_DIR"
chmod 600 "$APP_DIR/.env" 2>/dev/null || true
# ---- 3. dependencies, migrations, static files
say "Installing requirements"
"$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt
say "Checking the project"
"$PY" manage.py check
say "Migrating the database"
"$PY" manage.py migrate --noinput
say "Collecting static files"
"$PY" manage.py collectstatic --noinput --verbosity 0

# ---- 4. one-time catalogue load (exercises, pharmacy, labs, shop, ICD-10, assessment scales); all are safe to repeat
if [ ! -f "$APP_DIR/.catalogs_loaded" ] || [ "${LOAD_CATALOGS:-0}" = 1 ]; then
    say "Loading reference data (first deploy)"
    "$PY" manage.py load_icd10 && "$PY" manage.py load_exercises && "$PY" manage.py load_pharmacy \
        && "$PY" manage.py load_lab_catalog && "$PY" manage.py load_catalog && "$PY" manage.py load_scales
    date > "$APP_DIR/.catalogs_loaded"
fi

# ---- 5. restart (Passenger restarts when tmp/restart.txt changes)
say "Restarting the app"
mkdir -p "$APP_DIR/tmp" && touch "$APP_DIR/tmp/restart.txt"
say "Done. Open /healthz/ on your site: it should say {\"status\": \"ok\"}."
