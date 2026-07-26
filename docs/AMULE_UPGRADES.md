# Upgrading the pinned aMule build

This runbook governs upgrades of the aMule and wxWidgets source revisions used
by `docker/amuleapi/Dockerfile`. It intentionally does not track a branch or a
tag name at build time: every production image must be reproducible from full,
immutable commit IDs.

## Current baseline

| Component | Pinned revision | Role |
| --- | --- | --- |
| aMule | `7958b6926910b1f59b477b146bcf8882139f9558` | Development commit containing `amuleapi`. |
| wxWidgets | `5ff25322553c1870cf20a2e1ba6f20ed50d9fe9a` | Compatible source build with libcurl support. |

The latest aMule stable release observed on 2026-07-26 is
[`3.0.1`](https://github.com/amule-org/amule/releases/tag/3.0.1). Version 3.1
has not been released yet. Do not infer that an arbitrary post-release commit
is 3.1-compatible merely because it is on `master`.

## When to propose an update

Open a focused pull request only for one of these reasons:

- an upstream stable release includes a security, correctness or amuleapi fix;
- a pinned commit is needed to fix a reproducible aMulio compatibility issue;
- aMule 3.1 is released and has passed the validation gates below.

Never mix an upstream revision bump with unrelated aMulio behavior, dependency
or configuration changes. Keep the previous full commit IDs in the pull request
description, alongside the upstream release or commit URLs.

## Prepare the revision

Fetch tags and resolve a release tag to its final commit locally. An annotated
tag must be dereferenced before it is pinned:

```sh
git clone https://github.com/amule-org/amule.git /tmp/amulio-amule-upstream
git -C /tmp/amulio-amule-upstream fetch --tags --force
git -C /tmp/amulio-amule-upstream rev-parse 3.1.0^{}
git -C /tmp/amulio-amule-upstream show --no-patch --format=fuller 3.1.0^{}
```

Record the resulting 40-character SHA in `AMULE_REF`; do not put `3.1.0`,
`master` or a short SHA in the Dockerfile. Repeat the same process for
`WX_REF` only when upstream requirements make a wxWidgets change necessary.

Read the aMule release notes and the `amuleapi` source changes before editing.
In particular, review endpoint paths, authentication, search-session cleanup,
SSE event names, completed-file fields and configuration-file migrations. aMulio
depends on these as a control plane and must not silently assume backward
compatibility.

## Validation gate

In the pull request that changes a pin, all of the following must pass before
deployment:

```sh
docker build -f docker/amuleapi/Dockerfile -t amulio-amuleapi:candidate .
docker run --rm amulio-amuleapi:candidate amuled --version
uv run ruff check .
uv run pytest -rs --cov=amulio --cov-fail-under=82
docker compose --env-file .env.example config --quiet
```

CI independently builds both images, scans them with Trivy, audits Python
dependencies and runs CodeQL. It proves that the image compiles; it does not
replace the following live compatibility check with an authenticated aMule
control plane:

```sh
docker compose up --build -d
docker compose ps
docker compose exec amulio python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
docker compose down
```

For a change to amuleapi's behavior, also run the optional integration fixture
described in `tests/integration/README.md`, then verify a completed file can be
found by hash and served through a single HTTP Range request. Do not use real
media or production credentials in any test.

## Production rollout and rollback

1. Create and verify a backup using `docs/OPERATIONS.md`; preserve
   `amulio_amule_config`, the external secret files and Caddy state.
2. Record `git rev-parse HEAD`, the old `AMULE_REF`, and `docker compose ps`.
3. Build the candidate on the host: `docker compose build amuleapi`.
4. Replace only the aMule service: `docker compose up -d --no-deps amuleapi`.
   Wait for it to become healthy, then check the public `/health` endpoint and
   normal aMulio search/playback behavior.
5. If health, authentication, downloads, SSE state or completed-file playback
   regress, restore the recorded signed aMulio commit and recreate only
   `amuleapi`:

```sh
git checkout <previous-signed-commit>
docker compose build amuleapi
docker compose up -d --no-deps amuleapi
docker compose ps
```

Do not delete `amulio_amule_config`, `amulio_incoming` or `amulio_temp` during
an upstream rollback. The old image and persisted aMule configuration are the
recovery path; use the backup only if configuration migration prevents the old
binary from starting.
