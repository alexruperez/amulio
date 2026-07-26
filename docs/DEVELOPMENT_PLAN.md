# aMulio — Development Plan

This is the persistent, step-by-step development plan for **aMulio**, the
self-hosted Stremio addon backed by aMule and `amuleapi`.

## Product boundary

### v1 promise

1. A Stremio user opens a movie or series episode.
2. aMulio resolves its title, searches eD2K and Kad through aMule, and returns
   carefully ranked video candidates.
3. Selecting a new candidate queues its `ed2k://` link in aMule.
4. Selecting a candidate that is already complete streams the local file to
   Stremio with HTTP Range/seek support.

### Explicit v1 non-goal

Streaming an incomplete aMule `.part` file is not part of v1. `amuleapi`
exposes part-level availability but not a safe byte-range map or an operation
to prioritise a range requested by a player. Treat progressive playback as a
later, opt-in experiment.

## Current state

| Area | Status | Notes |
| --- | --- | --- |
| Stremio manifest and private installation URL | Done | Token is a bearer capability. |
| Cinemeta metadata lookup | Done | Resolves title/year or series episode scope. |
| aMule global and Kad search | Done | Uses authenticated `amuleapi` calls. |
| Candidate cache and filename ranking | Done | SQLite cache; title, year, episode, extension, quality and sources. |
| Signed playback URLs | Done | Credentials are never exposed to Stremio. |
| Completed-file playback | Done in code | Requires a real aMule/amuleapi instance and shared Incoming mount for integration validation. |
| Download/shared SSE subscription | Partial | Event state is tracked; bootstrap snapshots and `resync` recovery remain. |
| Downloading-state player UX | Not started | A selected unfinished stream currently returns HTTP 202; it needs a Stremio-friendly status video. |
| Reproducible aMule 3.1 image | Not started | Compose currently expects a supplied `AMULE_API_IMAGE`. |
| Production Caddy deployment | Not started | Local Compose only. |

## Development order

Work through these phases in order. Every phase has a concrete acceptance gate;
do not start the next one until the previous gate is satisfied.

## Phase 1 — Make discovery reliable

### 1.1 Add per-media search locks

- [ ] Use a keyed in-process lock for `movie:<imdb-id>` and
  `series:<imdb-id>:<season>:<episode>`.
- [ ] Return cached candidates immediately when a matching search is already
  running instead of launching duplicate global/Kad searches.
- [ ] Record a short negative-cache entry when no acceptable results are found.

**Acceptance:** ten concurrent requests for the same Stremio stream URL create
at most one global search and one Kad search in aMule.

### 1.2 Improve metadata and query generation

- [ ] Cache Cinemeta metadata with a TTL.
- [ ] Add title aliases, original titles and a configurable language preference.
- [ ] Generate a bounded set of queries: canonical title/year, original title,
  and exact `SxxEyy` variants for episodes.
- [ ] Enforce search timeouts and close stale aMule search sessions.

**Acceptance:** test fixtures cover films with translated titles and series
episodes whose filename uses `S02E04`, `2x04` or equivalent notation.

### 1.3 Harden ranking

- [ ] Add size plausibility ranges per type and detected quality.
- [ ] Detect season packs and reject them for an episode unless explicitly
  enabled.
- [ ] Add configurable extension allow/deny lists.
- [ ] Include language, codec, HDR and release-group signals in the score.
- [ ] Persist ranking fixtures collected from legal/public test names.

**Acceptance:** ranking tests reject archives, samples, wrong years and wrong
episodes while keeping the intended release at the top.

## Phase 2 — Make download state useful in Stremio

### 2.1 Complete SSE state reconciliation

- [ ] On startup, open the SSE stream, then take REST snapshots of downloads
  and shared files, then apply buffered events.
- [ ] Persist live `status`, percent, speed, sources and update timestamp for
  known hashes.
- [ ] Handle `resync` by invalidating state and repeating the snapshot flow.
- [ ] Reconnect with backoff and expose monitor health in `/health`.

**Acceptance:** restarting `amuleapi`, disconnecting it temporarily and
resuming it leaves aMulio with correct ready/downloading states without a
process restart.

### 2.2 Implement the Stremio downloading experience

- [ ] Add a small bundled, self-produced status video for “download started”,
  “still downloading” and “aMule unavailable”.
- [ ] Make `/play/{token}` return that media response instead of a raw HTTP
  202 when the file is not complete.
- [ ] Include percentage, speed and source count in the stream description on
  the next Stremio refresh.
- [ ] Make enqueueing idempotent by checking the file hash before submitting
  an eD2K link again.

**Acceptance:** selecting a new candidate starts exactly one aMule download and
Stremio displays a purposeful status video rather than a playback error.

## Phase 3 — Validate secure completed-file streaming

### 3.1 Build integration fixtures

- [ ] Run a real `amuled` + `amuleapi` fixture in Docker.
- [ ] Use a legal, small media fixture to validate completed-file discovery.
- [ ] Verify file movement from Temp to Incoming and hash-based re-resolution.

### 3.2 Test playback semantics

- [ ] Test `GET`, `HEAD`, single ranges, suffix ranges and invalid ranges.
- [ ] Test seeking before/after aMule completion acknowledgement.
- [ ] Test cancellation, simultaneous clients and a file disappearing during a
  request.
- [ ] Pin and regularly update a patched Starlette version with Range support.

### 3.3 Security review

- [ ] Test traversal, encoded traversal, symlink escape and non-regular files.
- [ ] Ensure every token has an expiry and cannot select an arbitrary path.
- [ ] Verify the container only mounts approved Incoming roots as read-only.
- [ ] Rate-limit manifest, stream and playback routes by installation token and
  client IP.

**Acceptance:** the integration suite proves correct `206`/`416` behavior and
cannot read any file outside the configured Incoming roots.

## Phase 4 — Ship a reproducible aMule stack

### 4.1 Build a pinned aMule/amuleapi image

- [ ] Add a multi-stage Dockerfile that compiles aMule from a pinned upstream
  commit with `BUILD_DAEMON=ON` and `BUILD_AMULEAPI=ON`.
- [ ] Run `amuled` and `amuleapi` under a non-root user.
- [ ] Bootstrap `amule.conf` and `amuleapi.conf` from Docker secrets with
  restrictive permissions.
- [ ] Keep EC and amuleapi ports internal only.

### 4.2 Complete Compose deployment

- [ ] Replace the placeholder `AMULE_API_IMAGE` flow with the local build.
- [ ] Add named volumes for aMule configuration, Temp and Incoming.
- [ ] Mount Incoming read-write to aMule and read-only to aMulio at identical
  paths.
- [ ] Add healthchecks and service dependency conditions.

**Acceptance:** a fresh host can start the full private stack with Docker
Compose and receives an authenticated `/health` response from aMulio.

## Phase 5 — Production operations

- [ ] Add Caddy with automatic HTTPS and no direct public aMule/amuleapi ports.
- [ ] Add structured logs, Prometheus metrics and a minimal `/metrics` policy.
- [ ] Add backup/restore instructions for configuration and cache; do not back
  up transient downloads by default.
- [ ] Add GitHub Actions for Ruff, tests, Docker build and image security scan.
- [ ] Document upgrades from pinned aMule commits to the eventual 3.1 release.

**Acceptance:** the deployment guide covers install, update, rollback, logs,
backup and incident diagnosis without requiring source-code knowledge.

## Phase 6 — Optional progressive playback experiment

Only start after v1 is stable and after an explicit decision to support it.

- [ ] Add a feature flag, disabled by default.
- [ ] Serve a range only when every byte in that range is known complete.
- [ ] Wait with bounded timeouts for missing ranges; never serve sparse-file
  zeroes as media content.
- [ ] Test MP4, MKV, AVI, startup, seeking and end-of-file metadata behavior.
- [ ] Propose upstream `amuleapi` support for exact completed intervals and
  download-range prioritisation if required.

**Acceptance:** the feature remains opt-in until playback tests demonstrate
reliable startup and seeking across supported clients.

## Next session starting point

Start with **Phase 1.1: per-media search locks**. It removes duplicate network
load and establishes the concurrency primitive that later cache and SSE work
will share.

Before changing behavior, run:

```sh
uv run ruff check .
uv run pytest
docker compose --env-file .env.example config
```
