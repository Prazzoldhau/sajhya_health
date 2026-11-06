#!/bin/bash
# Daily backup of Sajhya Health: the MySQL database AND the uploaded files (they refer to each other, so they are saved together).
#   bash ~/sajhya_health/deploy/backup.sh
# Run it every night from cPanel > Cron Jobs (see docs/OPERATIONS.md, "Backups and restore"), for example at 02:00:
#   0 2 * * *   bash $HOME/sajhya_health/deploy/backup.sh >> $HOME/backups/cron.log 2>&1
# What it does:
#   - dumps the database (consistent snapshot, nothing is locked for the users) and checks the dump really is complete
#   - packs media/ and private_uploads/ (patient pictures, credentials, lab reports)
#   - encrypts both when the file ~/.backup_passphrase exists (strongly advised: this is patient data)
#   - keeps 14 daily copies and 8 weekly copies (the Sunday backup), deleting older ones
#   - writes the date to ~/backups/daily/last_ok, so `manage.py deploy_doctor` can warn when backups stop
# Exit status is 1 when anything failed, so cPanel e-mails you the error.
# Settings (export before running to change):  APP_DIR (default ~/sajhya_health)   BACKUP_DIR (default ~/backups)   KEEP_DAILY (14)   KEEP_WEEKLY (8)
set -euo pipefail
umask 077

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAILY="${KEEP_DAILY:-14}"
KEEP_WEEKLY="${KEEP_WEEKLY:-8}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DAILY="$BACKUP_DIR/daily"
WEEKLY="$BACKUP_DIR/weekly"
PASSFILE="${BACKUP_PASSPHRASE_FILE:-$HOME/.backup_passphrase}"

say() { printf '%s  %s\n' "$(date '+%F %T')" "$*"; }
die() { printf '%s  ERROR: %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }

mkdir -p "$DAILY" "$WEEKLY"
[ -f "$APP_DIR/.env" ] || die "Missing $APP_DIR/.env"

# the database login, read from DATABASE_URL in .env (nothing is printed)
PY="${PY:-$(ls -d "$HOME/virtualenv/$(basename "$APP_DIR")"/*/bin/python 2>/dev/null | sort -V | tail -1 || true)}"
[ -n "$PY" ] && [ -x "$PY" ] || PY="$(command -v python3 || command -v python)"
eval "$($PY - "$APP_DIR/.env" <<'PYEOF'
import sys, urllib.parse
url = ''
for line in open(sys.argv[1], encoding='utf-8'):
    if line.startswith('DATABASE_URL='):
        url = line.split('=', 1)[1].strip().strip('"\'')
u = urllib.parse.urlparse(url)
if u.scheme.startswith('mysql'):
    q = lambda v: "'" + (v or '').replace("'", "'\\''") + "'"
    print(f"DB_NAME={q(u.path.lstrip('/'))}; DB_USER={q(urllib.parse.unquote(u.username or ''))}; DB_PASS={q(urllib.parse.unquote(u.password or ''))}; DB_HOST={q(u.hostname or 'localhost')}; DB_PORT={q(str(u.port or 3306))}; DB_KIND=mysql")
else:
    print("DB_KIND=other")
PYEOF
)"
[ "${DB_KIND:-other}" = mysql ] || die "DATABASE_URL in .env is not a MySQL address, so there is nothing to back up here."
command -v mysqldump >/dev/null 2>&1 || die "mysqldump is not available on this server."

ENC=""
if [ -s "$PASSFILE" ]; then
    command -v openssl >/dev/null 2>&1 || die "$PASSFILE exists but openssl is not available to encrypt with."
    ENC=".enc"
else
    say "WARNING: $PASSFILE not found, so the backups are NOT encrypted. Create it: head -c 32 /dev/urandom | base64 > ~/.backup_passphrase; chmod 600 ~/.backup_passphrase  (and keep a copy somewhere safe: without it the backups cannot be opened)"
fi

# encrypt (or just pass through) what comes in on stdin
protect() { if [ -n "$ENC" ]; then openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$PASSFILE"; else cat; fi; }

DB_OUT="$DAILY/db_$STAMP.sql.gz$ENC"
FILES_OUT="$DAILY/files_$STAMP.tar.gz$ENC"
cleanup_partial() { rm -f "${DB_OUT:-}" "${FILES_OUT:-}" "$DAILY/.dump_check" 2>/dev/null || true; }
trap 'rc=$?; if [ $rc -ne 0 ]; then cleanup_partial; fi' EXIT

# 1. the database. The dump goes to a temporary plain file first so it can be checked before it is encrypted.
say "Dumping database $DB_NAME"
TMP="$DAILY/.dump_check"
MYSQL_PWD="$DB_PASS" mysqldump --single-transaction --quick --no-tablespaces --routines --default-character-set=utf8mb4 \
    -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" "$DB_NAME" > "$TMP" || die "mysqldump failed."
tail -n 3 "$TMP" | grep -q "Dump completed" || die "The database dump is incomplete (no 'Dump completed' line)."
[ "$(wc -c < "$TMP")" -gt 5000 ] || die "The database dump is suspiciously small."
TABLES="$(grep -c '^CREATE TABLE' "$TMP" || true)"
gzip -c "$TMP" | protect > "$DB_OUT"
rm -f "$TMP"
say "Saved $(basename "$DB_OUT") ($(du -h "$DB_OUT" | cut -f1), $TABLES tables)"

# 2. the uploaded files
say "Packing uploaded files"
DIRS=()
for d in media private_uploads; do [ -d "$APP_DIR/$d" ] && DIRS+=("$d"); done
if [ "${PRIVATE_MEDIA_ROOT:-}" ] && [ -d "$PRIVATE_MEDIA_ROOT" ]; then say "NOTE: PRIVATE_MEDIA_ROOT is set to $PRIVATE_MEDIA_ROOT, which is outside the app folder: back that folder up too."; fi
if [ "${#DIRS[@]}" -gt 0 ]; then
    tar -C "$APP_DIR" -czf - "${DIRS[@]}" | protect > "$FILES_OUT"
    say "Saved $(basename "$FILES_OUT") ($(du -h "$FILES_OUT" | cut -f1), folders: ${DIRS[*]})"
else
    say "No media folders found: nothing to pack."
    FILES_OUT=""
fi

# 3. a copy of Sunday's backup is kept for 8 weeks
if [ "$(date +%u)" = 7 ]; then
    cp "$DB_OUT" "$WEEKLY/"; [ -n "$FILES_OUT" ] && cp "$FILES_OUT" "$WEEKLY/"
    say "Kept a weekly copy"
fi

# 4. delete old ones: the newest KEEP_DAILY of each kind, the newest KEEP_WEEKLY weekly ones
prune() { { ls -1t "$1"/$2 2>/dev/null || true; } | tail -n +"$(( $3 + 1 ))" | xargs -r rm -f; }
prune "$DAILY" 'db_*' "$KEEP_DAILY";    prune "$DAILY" 'files_*' "$KEEP_DAILY"
prune "$WEEKLY" 'db_*' "$KEEP_WEEKLY";  prune "$WEEKLY" 'files_*' "$KEEP_WEEKLY"

date '+%F %T' > "$DAILY/last_ok"
say "Backup finished. Newest copies are in $DAILY. Copy them off this server regularly (download from cPanel File Manager, or sync to another place): a backup on the same server is lost with the server."
