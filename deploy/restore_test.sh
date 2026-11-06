#!/bin/bash
# Proves a backup can really be restored: loads the newest database backup into an EMPTY SCRATCH database and compares it with the live one.
# It never touches the live database and never overwrites anything.
#   1. cPanel > MySQL Databases: create a scratch database (for example <account>_restoretest) and add your app's database user to it (ALL PRIVILEGES).
#   2. bash ~/sajhya_health/deploy/restore_test.sh <account>_restoretest            (newest backup)
#      bash ~/sajhya_health/deploy/restore_test.sh <account>_restoretest ~/backups/daily/db_20261106_020000.sql.gz.enc    (a chosen one)
#   3. Read the table at the end. Row counts in the scratch copy can be a little lower than the live ones (people used the app since the backup); a big gap or an empty table is a problem.
# The scratch database is emptied again afterwards. Add --keep to leave it loaded so you can look at it.
set -euo pipefail
umask 077

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
PASSFILE="${BACKUP_PASSPHRASE_FILE:-$HOME/.backup_passphrase}"
SCRATCH="${1:-}"; FILE="${2:-}"; KEEP=0
for a in "$@"; do [ "$a" = "--keep" ] && KEEP=1; done
[ "$FILE" = "--keep" ] && FILE=""
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ -n "$SCRATCH" ] && [ "$SCRATCH" != "--keep" ] || die "Give the name of the empty scratch database: bash deploy/restore_test.sh <account>_restoretest"

PY="${PY:-$(ls -d "$HOME/virtualenv/$(basename "$APP_DIR")"/*/bin/python 2>/dev/null | sort -V | tail -1 || true)}"
[ -n "$PY" ] && [ -x "$PY" ] || PY="$(command -v python3 || command -v python)"
eval "$($PY - "$APP_DIR/.env" <<'PYEOF'
import sys, urllib.parse
url = ''
for line in open(sys.argv[1], encoding='utf-8'):
    if line.startswith('DATABASE_URL='):
        url = line.split('=', 1)[1].strip().strip('"\'')
u = urllib.parse.urlparse(url)
q = lambda v: "'" + (v or '').replace("'", "'\\''") + "'"
print(f"DB_NAME={q(u.path.lstrip('/'))}; DB_USER={q(urllib.parse.unquote(u.username or ''))}; DB_PASS={q(urllib.parse.unquote(u.password or ''))}; DB_HOST={q(u.hostname or 'localhost')}; DB_PORT={q(str(u.port or 3306))}")
PYEOF
)"
[ "$SCRATCH" != "$DB_NAME" ] || die "$SCRATCH is the LIVE database. Use a separate scratch database."
export MYSQL_PWD="$DB_PASS"
my() { mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" "$@"; }

[ -n "$FILE" ] || FILE="$(ls -1t "$BACKUP_DIR"/daily/db_* 2>/dev/null | head -1 || true)"
[ -n "$FILE" ] && [ -f "$FILE" ] || die "No database backup found in $BACKUP_DIR/daily. Run deploy/backup.sh first."
echo "Backup: $FILE ($(du -h "$FILE" | cut -f1), $(date -r "$FILE" '+%F %T'))"

# the scratch database must be empty, so nothing of value can be lost
COUNT="$(my -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$SCRATCH'" 2>/dev/null)" || die "Cannot reach the scratch database $SCRATCH (is it created, and is $DB_USER added to it?)."
[ "$COUNT" = 0 ] || die "$SCRATCH is not empty ($COUNT tables). Use an empty scratch database."

reader() { case "$FILE" in *.enc) openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$PASSFILE" < "$FILE" ;; *) cat "$FILE" ;; esac; }
echo "Restoring into $SCRATCH ..."
reader | gunzip | my --default-character-set=utf8mb4 "$SCRATCH" || die "The backup could not be loaded. It may be damaged, or the passphrase file is not the one used for it."

TABLES="$(my -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$SCRATCH'")"
echo "Restored $TABLES tables. Comparing row counts (live vs restored):"
printf '%-34s %10s %10s\n' TABLE LIVE RESTORED
BAD=0
for t in accounts_patient accounts_professionalprofile billing_billingentry billing_entrypayment billing_patientpackage billing_patientadvance soapnotes_soapnote auth_user; do
    live="$(my -N -e "SELECT COUNT(*) FROM \`$DB_NAME\`.\`$t\`" 2>/dev/null || echo n/a)"
    rest="$(my -N -e "SELECT COUNT(*) FROM \`$SCRATCH\`.\`$t\`" 2>/dev/null || echo n/a)"
    flag=""; if [ "$live" != n/a ] && [ "$live" -gt 0 ] && { [ "$rest" = n/a ] || [ "$rest" = 0 ]; }; then flag="  <-- EMPTY, PROBLEM"; BAD=1; fi
    printf '%-34s %10s %10s%s\n' "$t" "$live" "$rest" "$flag"
done

if [ "$KEEP" = 1 ]; then
    echo "Left the restored copy in $SCRATCH (--keep). Empty it before the next test."
else
    echo "Emptying $SCRATCH ..."
    my -N -e "SELECT CONCAT('DROP TABLE IF EXISTS \`',table_name,'\`;') FROM information_schema.tables WHERE table_schema='$SCRATCH'" | { echo "SET FOREIGN_KEY_CHECKS=0;"; cat; } | my "$SCRATCH"
fi

# the file backup: just prove it can be read
FFILE="$(ls -1t "$BACKUP_DIR"/daily/files_* 2>/dev/null | head -1 || true)"
if [ -n "$FFILE" ]; then
    case "$FFILE" in *.enc) n="$(openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$PASSFILE" < "$FFILE" | tar -tzf - | wc -l)" ;; *) n="$(tar -tzf "$FFILE" | wc -l)" ;; esac
    echo "Files backup $(basename "$FFILE") opens fine and holds $n entries."
fi
[ "$BAD" = 0 ] && echo "RESULT: the backup restores correctly." || { echo "RESULT: PROBLEM - a table that has rows live came back empty."; exit 1; }
