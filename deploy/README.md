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
