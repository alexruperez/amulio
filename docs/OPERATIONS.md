# aMulio operations guide

Run every command below from the root of the checked-out aMulio repository.
The Compose project is explicitly named `amulio`, so the named volumes in this
guide have stable names. Do not use `docker compose down --volumes` during a
normal update: it deletes persistent state.

## What is persistent

| Volume or file | Keep in normal backup? | Reason |
| --- | --- | --- |
| `amulio_amule_config` | Yes | aMule identity and configuration. |
| `amulio_amulio_data` | Yes | aMulio SQLite candidate and download-state cache. |
| `amulio_caddy_data`, `amulio_caddy_config` | Yes, encrypted | TLS certificates and Caddy state. |
| `secrets/amule_ec_password`, `secrets/amuleapi_admin_password`, `.env` | Yes, encrypted and outside Git | Credentials and installation/signing tokens. |
| `amulio_temp` | No | Incomplete, transient aMule parts. |
| `amulio_incoming` | Optional, separate media backup | Completed media can be large and may have its own retention policy. |

Back up both the persistent volumes and the external secrets. A restored
configuration without the original secrets will not reconnect to the existing
aMule instance or preserve existing private Stremio URLs.

## Backup

Choose a location on encrypted storage that is not inside this repository. The
following keeps the services online; the SQLite cache may be a few seconds out
of date, which is safe because aMulio rebuilds it from amuleapi.

```sh
export BACKUP_DIR=/srv/backups/amulio/$(date +%F)
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

for volume in amulio_amule_config amulio_amulio_data amulio_caddy_data amulio_caddy_config; do
  docker volume inspect "$volume" >/dev/null
  docker run --rm \
    -v "$volume":/source:ro \
    -v "$BACKUP_DIR":/backup \
    alpine:3.21 \
    tar -C /source -cpf "/backup/${volume}.tar" .
done

cp .env secrets/amule_ec_password secrets/amuleapi_admin_password "$BACKUP_DIR"/
chmod 600 "$BACKUP_DIR"/*
```

Store the directory with an encrypted backup system. Caddy's data contains TLS
private keys, and `.env` contains bearer credentials. Do not commit archives or
secret files. To include completed media, back up `amulio_incoming` separately
only when its content and storage cost are within your policy; never include
`amulio_temp` as a recovery strategy.

For a crash-consistent cache snapshot, briefly stop only aMulio before the loop
and start it again afterwards:

```sh
docker compose stop amulio
# Run the backup loop above.
docker compose start amulio
```

## Restore

Restoring overwrites the four persistent volumes. Confirm the backup date and
keep a current backup before proceeding. The commands intentionally name every
target volume; they do not use a wildcard or `docker compose down --volumes`.

```sh
export BACKUP_DIR=/srv/backups/amulio/2026-01-31
test -f "$BACKUP_DIR/amulio_amule_config.tar"
test -f "$BACKUP_DIR/.env"

docker compose down
docker volume rm \
  amulio_amule_config amulio_amulio_data amulio_caddy_data amulio_caddy_config

for volume in amulio_amule_config amulio_amulio_data amulio_caddy_data amulio_caddy_config; do
  docker volume create "$volume"
  docker run --rm \
    -v "$volume":/target \
    -v "$BACKUP_DIR":/backup:ro \
    alpine:3.21 \
    tar -C /target -xpf "/backup/${volume}.tar"
done

install -m 600 "$BACKUP_DIR/.env" .env
install -d -m 700 secrets
install -m 600 "$BACKUP_DIR/amule_ec_password" secrets/amule_ec_password
install -m 600 "$BACKUP_DIR/amuleapi_admin_password" secrets/amuleapi_admin_password
docker compose up --build -d
docker compose ps
```

Do not restore the cache alone to a different aMule configuration: it contains
only disposable hints, so omit `amulio_amulio_data` instead if the aMule state
is intentionally new. Restoring Incoming media is separate; mount or restore it
only after validating ownership and available storage.

## Update and rollback

Before changing the checkout, create a backup as above and record the currently
running revision:

```sh
git rev-parse HEAD
docker compose ps
```

Update with a short, reversible service restart:

```sh
git pull --ff-only
docker compose build
docker compose up -d --remove-orphans
docker compose ps
docker compose logs --tail=100 amulio amuleapi caddy
```

If a new revision fails, return to the recorded commit and recreate only the
containers. Persistent volumes remain intact:

```sh
git checkout <previous-signed-commit>
docker compose build
docker compose up -d --remove-orphans
docker compose ps
```

Use `git switch main` followed by `git pull --ff-only` when ready to return to
the current release. Do not use `git reset --hard` on a host that contains local
deployment changes.

## Updating the pinned aMule build

aMulio deliberately builds aMule from immutable full Git commit IDs, rather
than following `master` or a mutable tag. At the time this guide was written,
the latest upstream stable release is `3.0.1`; `3.1` is not yet a published
release. See [the dedicated aMule upgrade runbook](AMULE_UPGRADES.md) before
changing `AMULE_REF` or `WX_REF` in `docker/amuleapi/Dockerfile`.

## Health checks and incident diagnosis

Start with container state and recent logs:

```sh
docker compose ps
docker compose logs --tail=200 amulio amuleapi caddy
```

Expected state: `caddy` publishes ports 80/443, `amulio` is healthy, and
`amuleapi` is healthy but has no host port. The public endpoint is the Caddy
domain, so verify it without printing the private installation URL:

```sh
curl --fail --silent --show-error https://"$CADDY_DOMAIN"/health
```

Common signals:

- Caddy cannot obtain a certificate: ensure `CADDY_DOMAIN` resolves to this
  host and ports 80 and 443 are reachable from the Internet.
- aMulio reports HTTP 503: inspect `amuleapi` logs, then confirm the two secret
  files exist and retain mode `600`.
- Stremio cannot play a completed file: confirm it exists in
  `amulio_incoming`, then inspect aMule's shared-file state. Do not expose
  amuleapi to investigate it remotely.
- Metrics return 404: this is expected until `AMULIO_METRICS_TOKEN` is set;
  scrape with its Bearer token only from a trusted monitoring system.
