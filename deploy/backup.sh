#!/usr/bin/env bash
# Nightly off-site backup: dump the database, encrypt it so only the owner's
# private key can read it, copy it to Cloudflare R2, prove it is there, and
# prune old copies. Run by cron (see deploy/README.md), or by hand to test.
#
# Settings are read from the server's .env (never echoed):
#   BACKUP_AGE_RECIPIENT   the owner's age PUBLIC key (starts "age1"); the
#                          matching private key never touches this server
#   R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
#   R2_BUCKET              optional, default agyary-backups
#   BACKUP_HEARTBEAT_URL   optional; its own healthchecks.io check, pinged only after a verified upload
#   BACKUP_KEEP_DAYS       optional, default 30
set -euo pipefail
# Anything this writes (the plain dump before it is encrypted) is for this user only.
umask 077

cd "$(dirname "$0")/.."

env_get() {  # env_get NAME -> value from .env (empty if absent), without sourcing the file
  { grep -E "^$1=" .env || true; } | tail -n1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}

recipient=$(env_get BACKUP_AGE_RECIPIENT)
account=$(env_get R2_ACCOUNT_ID)
key_id=$(env_get R2_ACCESS_KEY_ID)
secret=$(env_get R2_SECRET_ACCESS_KEY)
bucket=$(env_get R2_BUCKET); bucket=${bucket:-agyary-backups}
keep=$(env_get BACKUP_KEEP_DAYS); keep=${keep:-30}
heartbeat=$(env_get BACKUP_HEARTBEAT_URL)

for name in recipient account key_id secret; do
  [ -n "${!name}" ] || { echo "backup: ${name} is not set in .env" >&2; exit 2; }
done
case "${recipient}" in age1*) ;; *) echo "backup: BACKUP_AGE_RECIPIENT must be an age public key (age1...)" >&2; exit 2 ;; esac
command -v rclone >/dev/null || { echo "backup: rclone is not installed (sudo apt install rclone)" >&2; exit 2; }

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="${key_id}"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="${secret}"
export RCLONE_CONFIG_R2_ENDPOINT="https://${account}.r2.cloudflarestorage.com"
export RCLONE_CONFIG_R2_ACL=private
# The token is limited to this one bucket, so rclone must not try to create it.
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true

stamp=$(date -u +%Y%m%dT%H%M%SZ)
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
dump="${work}/agyary-${stamp}.dump"
sealed="${dump}.age"

echo "==> dumping"
docker compose exec -T db pg_dump -U agyary -d agyary -Fc > "${dump}"
# A dump you have not listed is not a backup.
tables=$(docker compose exec -T db pg_restore -l < "${dump}" | grep -c "TABLE DATA" || true)
if [ "${tables}" -lt 1 ]; then
  echo "backup: the dump is unreadable; nothing uploaded" >&2
  exit 1
fi

echo "==> encrypting (${tables} tables of data)"
age -r "${recipient}" -o "${sealed}" "${dump}"
rm -f "${dump}"

echo "==> uploading"
rclone copyto "${sealed}" "R2:${bucket}/daily/$(basename "${sealed}")"
# Check it landed with the right size before calling this a backup.
want=$(stat -c %s "${sealed}")
got=$(rclone size --json "R2:${bucket}/daily/$(basename "${sealed}")" | grep -o '"bytes":[0-9]*' | cut -d: -f2)
if [ "${want}" != "${got}" ]; then
  echo "backup: uploaded size ${got} does not match ${want}" >&2
  exit 1
fi

echo "==> pruning copies older than ${keep} days"
rclone delete "R2:${bucket}/daily" --min-age "${keep}d"

[ -n "${heartbeat}" ] && curl -fsS -m 10 --retry 2 -o /dev/null "${heartbeat}" || true
echo "backup ok: $(basename "${sealed}") (${want} bytes)"
