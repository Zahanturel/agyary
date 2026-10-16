# Automatic deploys

Every push to `master` runs `.github/workflows/deploy.yml`: the tests, then -
only if they pass - a deploy to the VM (`deploy/deploy.sh`: back up, build,
migrate with the new image, swap, wait for `/health`). A failed migration or an
unhealthy app fails the run and, for a migration, leaves the old version
serving. Pull requests run the tests only and never see the secrets.

## One-time setup

1. **A deploy key, not your own.** On your machine:
   `ssh-keygen -t ed25519 -f deploy_key -N "" -C github-deploy`
   Append `deploy_key.pub` to `~/.ssh/authorized_keys` on the VM. Delete the
   local files after step 2.
2. **GitHub -> repo Settings -> Secrets and variables -> Actions**, add:
   - `VM_HOST` - the VM's address
   - `VM_USER` - the SSH user
   - `VM_SSH_KEY` - the contents of `deploy_key` (the private half)
   - `VM_KNOWN_HOSTS` - the output of `ssh-keyscan -t ed25519 <VM_HOST>`
3. Optional but sensible: Settings -> Environments -> `production` -> require
   a reviewer, if you want a tap-to-approve before each deploy.

These live in GitHub's secrets, never in the repo (it is public).

To revoke access, remove that one line from the VM's `authorized_keys`.

# Nightly off-site backups

`deploy/backup.sh` dumps the database, encrypts it with the owner's age
**public** key, uploads it to a private Cloudflare R2 bucket, checks the upload,
and deletes copies older than 30 days. The server can write backups but cannot
read them: the private key lives only with the owner.

## One-time setup

1. **A key pair, on the owner's own machine** (not the server):
   `age-keygen -o agyary-backup.key` (Windows: `winget install FiloSottile.age`).
   It prints `Public key: age1...`. Keep `agyary-backup.key` in a password
   manager and on paper or a USB stick; lose it and every backup is unreadable.
2. **R2**: create a private bucket `agyary-backups`, then an API token with
   *Object Read & Write* on that bucket only.
3. **On the VM**: `sudo apt install rclone`, then add to `.env`:
   `BACKUP_AGE_RECIPIENT`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
   `R2_SECRET_ACCESS_KEY` (and optionally `BACKUP_HEARTBEAT_URL`, a separate
   healthchecks.io check from `HEARTBEAT_URL`).
4. Try it once by hand: `~/agyary/deploy/backup.sh`.
5. Schedule it (03:30 IST = 22:00 UTC): `crontab -e`, then
   `0 22 * * * $HOME/agyary/deploy/backup.sh >> $HOME/agyary-backup.log 2>&1`

## Restore drill (do this once, then every few months)

On a machine that has the private key and a scratch Postgres (never production):

    rclone copyto R2:agyary-backups/daily/<file>.dump.age .   # or download in the dashboard
    age -d -i agyary-backup.key -o restore.dump <file>.dump.age
    pg_restore -l restore.dump | grep -c "TABLE DATA"          # expect 25
    createdb scratch && pg_restore -d scratch restore.dump

A backup that has never been restored is a hope, not a backup.
