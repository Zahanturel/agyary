#!/usr/bin/env bash
# Deploy the checked-out code on the VM. Run from anywhere; it works in the
# repo it lives in. CI calls this after `git pull`; you can run it by hand too.
#
# Order matters and is chosen so a failure leaves the OLD version serving:
#   1. back up the database (kept: the newest 10)
#   2. build the new image
#   3. migrate with the NEW image, before it serves anything
#   4. swap the app over
#   5. wait for /health, and fail loudly if it never comes
# A failed migration stops at step 3 with the old container still running.
set -euo pipefail

cd "$(dirname "$0")/.."

stamp=$(date +%Y%m%d-%H%M%S)
backup="$HOME/agyary-${stamp}-deploy.dump"

echo "==> backing up to ${backup}"
docker compose exec -T db pg_dump -U agyary -d agyary -Fc > "${backup}"
# A dump you have not listed is not a backup.
tables=$(docker compose exec -T db pg_restore -l < "${backup}" | grep -c "TABLE DATA" || true)
if [ "${tables}" -lt 1 ]; then
  echo "backup is unreadable; refusing to deploy" >&2
  rm -f "${backup}"
  exit 1
fi
ls -1t "$HOME"/agyary-*-deploy.dump 2>/dev/null | tail -n +11 | xargs -r rm -f

echo "==> building"
docker compose build app

echo "==> migrating"
docker compose run --rm --no-deps app uv run alembic upgrade head

echo "==> starting"
docker compose up -d app

echo "==> waiting for health"
for i in $(seq 1 30); do
  status=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q app)" 2>/dev/null || echo starting)
  if [ "${status}" = "healthy" ]; then
    echo "deployed $(git rev-parse --short HEAD)"
    exit 0
  fi
  sleep 3
done

echo "app did not become healthy; last logs:" >&2
docker compose logs --tail 40 app >&2
echo "backup from before this deploy: ${backup}" >&2
exit 1
