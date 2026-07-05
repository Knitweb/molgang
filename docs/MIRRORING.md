# Mirroring: GitHub → GitLab → Radicle

This repo is mirrored to two secondary forges for redundancy and sovereignty:

- **GitHub** — primary (CI, PRs).
- **GitLab** — hot mirror via CI (`.github/workflows/mirror.yml`).
- **Radicle** — sovereign P2P publication via `scripts/mirror-remotes.sh` (local).

## GitLab (CI push-mirror)

The `mirror` workflow force-pushes `main` (and tags) to GitLab on every push. It
is **guarded** — with no configuration it just prints a notice and succeeds.

To activate:

1. Create the GitLab project (empty): `glab repo create <namespace>/molgang --private`
2. Create a **project access token** with `write_repository` scope.
3. In the GitHub repo settings add:
   - Actions **secret** `GITLAB_TOKEN` = the token
   - Actions **variable** `GITLAB_PATH` = `<namespace>/molgang`
   - (optional) Actions **variable** `GITLAB_HOST` = `gitlab.com` (default) or a self-hosted host

Next push to `main` mirrors automatically.

## Radicle (sovereign, local)

The Radicle node signing key **must not** be placed in CI (a leaked key is what
the PLS *burn-on-exposure* rule punishes). Publish and sync from a trusted machine:

```bash
rad auth                                   # once per machine (identity + passphrase)
rad init --public --name molgang --default-branch main
rad push                                   # announce to seeds (e.g. the 5mart.ml relay)
```

Then keep it in sync (cron or the node loop):

```bash
GITLAB_TOKEN=… GITLAB_PATH=… scripts/mirror-remotes.sh   # pushes GitLab + rad sync
```

`scripts/mirror-remotes.sh` skips any target that isn't configured, so it is safe
to run anywhere.

See the full rollout plan for all repos in
`~/Cleopatra/knitweb/design/gitlab_radicle_automation_plan.md`.
