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
| Completed-file playback | Done and validated | Public HTTPS E2E test completed with Stremio Web and byte-range playback. |
| Completed local-file discovery | Done and validated | Incoming files are matched to Cinemeta titles and shown as web-ready streams. |
| Download/shared SSE subscription | Done | Snapshot-then-stream reconciliation, `resync` recovery and monitor health are persisted. |
| Downloading-state player UX | Done | Bundled status videos, live stream metadata and idempotent enqueueing. |
| Reproducible aMule 3.1 image | Done | Multi-stage local build pins the upstream aMule and wxWidgets commits. |
| Production Caddy deployment | Done for test instance | Caddy exposes HTTPS while EC and amuleapi remain private. |
| Configuration experience | Prototype only | Functional install URL, but no settings model or production-quality UI. |
| Branding and localisation | Not started | Manifest has no logo and user-facing strings are mixed-language. |
| Click-to-download E2E | Implemented in code, not product-validated | Selecting a remote candidate queues it idempotently; the complete real-network journey still needs validation. |
| Home Assistant app | Research complete; not started | Feasible as a single supervised image for `amuled`, `amuleapi` and aMulio. |

## Development order

Work through these phases in order. Every phase has a concrete acceptance gate;
do not start the next one until the previous gate is satisfied.

## Phase 1 — Make discovery reliable

### 1.1 Add per-media search locks

- [x] Use a keyed in-process lock for `movie:<imdb-id>` and
  `series:<imdb-id>:<season>:<episode>`.
- [x] Return cached candidates immediately when a matching search is already
  running instead of launching duplicate global/Kad searches.
- [x] Record a short negative-cache entry when no acceptable results are found.

**Acceptance:** ten concurrent requests for the same Stremio stream URL create
at most one global search and one Kad search in aMule.

### 1.2 Improve metadata and query generation

- [x] Cache Cinemeta metadata with a TTL.
- [x] Add title aliases, original titles and a configurable language preference.
- [x] Generate a bounded set of queries: canonical title/year, original title,
  and exact `SxxEyy` variants for episodes.
- [x] Enforce a bounded timeout for each discovery cycle.
- [x] Close stale aMule search sessions with `POST /search/stop` and
  `close: true`, validated against the upstream aMule 3.1 `amuleapi` source.

**Acceptance:** test fixtures cover films with translated titles and series
episodes whose filename uses `S02E04`, `2x04` or equivalent notation.

### 1.3 Harden ranking

- [x] Add size plausibility ranges per type and detected quality.
- [x] Detect season packs and reject them for an episode unless explicitly
  enabled.
- [x] Add configurable extension allow/deny lists.
- [x] Include language, codec, HDR and release-group signals in the score.
- [x] Persist ranking fixtures collected from legal/public test names.

**Acceptance:** ranking tests reject archives, samples, wrong years and wrong
episodes while keeping the intended release at the top.

## Phase 2 — Make download state useful in Stremio

### 2.1 Complete SSE state reconciliation

- [x] On startup, open the SSE stream, then take REST snapshots of downloads
  and shared files, then apply buffered events.
- [x] Persist live `status`, percent, speed, sources and update timestamp for
  known hashes.
- [x] Handle `resync` by invalidating state and repeating the snapshot flow.
- [x] Reconnect with backoff and expose monitor health in `/health`.

**Acceptance:** restarting `amuleapi`, disconnecting it temporarily and
resuming it leaves aMulio with correct ready/downloading states without a
process restart.

### 2.2 Implement the Stremio downloading experience

- [x] Add a small bundled, self-produced status video for “download started”,
  “still downloading” and “aMule unavailable”.
- [x] Make `/play/{token}` return that media response instead of a raw HTTP
  202 when the file is not complete.
- [x] Include percentage, speed and source count in the stream description on
  the next Stremio refresh.
- [x] Make enqueueing idempotent by checking the file hash before submitting
  an eD2K link again.

**Acceptance:** selecting a new candidate starts exactly one aMule download and
Stremio displays a purposeful status video rather than a playback error.

## Phase 3 — Validate secure completed-file streaming

### 3.1 Build integration fixtures

- [x] Run a real `amuled` + `amuleapi` fixture in Docker.
- [x] Use a self-produced, small MP4 fixture to validate completed-file discovery.
- [x] Verify hash-based re-resolution through a shared Incoming mount.

### 3.2 Test playback semantics

- [x] Test `GET`, `HEAD`, single ranges, suffix ranges and invalid ranges.
- [x] Test seeking before/after aMule completion acknowledgement.
- [x] Test cancellation, simultaneous clients and a file disappearing during a
  request.
- [x] Pin Starlette to a patched release with Range support.

### 3.3 Security review

- [x] Test traversal, encoded traversal, symlink escape and non-regular files.
- [x] Ensure every token has an expiry and cannot select an arbitrary path.
- [x] Verify the container only mounts approved Incoming roots as read-only.
- [x] Rate-limit manifest, stream and playback routes by installation token and
  client IP.

**Acceptance:** the integration suite proves correct `206`/`416` behavior and
cannot read any file outside the configured Incoming roots.

## Phase 4 — Ship a reproducible aMule stack

### 4.1 Build a pinned aMule/amuleapi image

- [x] Add a multi-stage Dockerfile that compiles aMule from a pinned upstream
  commit with `BUILD_DAEMON=ON` and `BUILD_AMULEAPI=ON`.
- [x] Run `amuled` and `amuleapi` under a non-root user.
- [x] Bootstrap `amule.conf` and `amuleapi.conf` from Docker secrets with
  restrictive permissions.
- [x] Keep EC and amuleapi ports internal only.

### 4.2 Complete Compose deployment

- [x] Replace the placeholder `AMULE_API_IMAGE` flow with the local build.
- [x] Add named volumes for aMule configuration, Temp and Incoming.
- [x] Mount Incoming read-write to aMule and read-only to aMulio at identical
  paths.
- [x] Add healthchecks and service dependency conditions.

**Acceptance:** a fresh host can start the full private stack with Docker
Compose and receives an authenticated `/health` response from aMulio.

## Phase 5 — Production operations

- [x] Add Caddy with automatic HTTPS and no direct public aMule/amuleapi ports.
- [x] Add structured logs, Prometheus metrics and a minimal `/metrics` policy.
- [x] Add backup/restore instructions for configuration and cache; do not back
  up transient downloads by default.
- [x] Add GitHub Actions for Ruff, tests, Docker build and image security scan.
- [x] Document upgrades from pinned aMule commits to the eventual 3.1 release.

**Acceptance:** the deployment guide covers install, update, rollback, logs,
backup and incident diagnosis without requiring source-code knowledge.

## MVP feedback research and product decisions

The July 2026 public E2E test proved that Stremio can discover and play a
completed file through aMulio. It also exposed the following MVP gaps, which
take priority over incomplete `.part` playback.

### Configuration UX

[Torrentio](https://torrentio.strem.fun/configure) and
[Comet](https://comet.elfhosted.com/configure) both use a branded, responsive
configuration page with grouped controls, useful defaults, an explicit
**Install** action and a **Copy link** fallback. Comet additionally hides
secondary options in progressive sections so the initial experience stays
approachable.

aMulio will adopt those product patterns without copying their visual assets
or source:

- a branded header, short explanation and live readiness summary;
- grouped Basic, Search, Language, Storage and Advanced sections;
- validation beside the field that needs attention;
- a primary **Install in Stremio** button and secondary **Copy manifest URL**;
- a mobile-first responsive layout, keyboard navigation and accessible labels;
- no EC password, amuleapi credential or token displayed unnecessarily.

Stremio only redirects to `/configure` when the manifest is declared
configurable. Its
[manifest documentation](https://stremio.github.io/stremio-addon-sdk/api/responses/manifest.html)
requires actual user configuration for that mode, and its
[advanced guide](https://stremio.github.io/stremio-addon-sdk/advanced.html)
expects the page to generate an installable manifest URL. aMulio must never
reintroduce the configuration loop found during the E2E test.

### Branding and language

- Use the official aMule artwork from
  [`src/icons/amule.png`](https://github.com/amule-project/amule/blob/master/src/icons/amule.png)
  for the Stremio manifest and configuration UI.
- Record its upstream provenance and GPL-2.0 asset licensing separately from
  aMulio's Apache-2.0 code before shipping the copied asset.
- Add `logo` and, if an appropriate original is available, `background` to the
  manifest.
- Make English the source language and default for the configuration page,
  manifest, streams, status videos, errors and documentation examples.
- Add Spanish as the first complete translation. All new UI strings must use
  translation keys rather than inline prose.
- Let the user select UI language independently from preferred search-result
  languages.

### “Download with aMule” semantics

Stremio stream addons do not expose arbitrary action buttons in a stream row.
The compatible interaction is to return a remote candidate as a stream and
make selecting it call `/play/{token}`. aMulio already uses that hook to submit
an eD2K link exactly once. The MVP must make the action explicit:

1. A completed local result is labelled **Ready to play**.
2. A remote result is labelled **Download with aMule** and includes size,
   quality and source availability.
3. Selecting it queues the link idempotently and plays a short English status
   video confirming that the download started.
4. Reopening the title shows current percentage, speed and sources.
5. Once complete, the same result becomes **Ready to play** and serves HTTP
   ranges.

This is analogous to a debrid cache request at the UX level, but aMule may take
materially longer and the interface must set that expectation honestly.

### Home Assistant distribution

Home Assistant now calls add-ons **apps**. Its
[app tutorial](https://developers.home-assistant.io/docs/apps/tutorial/) and
[configuration reference](https://developers.home-assistant.io/docs/apps/configuration/)
support published multi-architecture container images, persistent `/data`,
translated options, mapped media folders and declared TCP/UDP ports.

The proposed aMulio Home Assistant app will:

- ship `amuled`, `amuleapi` and aMulio in one image supervised as separate
  processes; it will not require Docker API access or Docker Compose inside the
  app;
- support `amd64` and `aarch64`, publish versioned GHCR images and use the Home
  Assistant builder/signing workflow;
- keep configuration, Temp and Incoming data under persistent app storage,
  optionally map `/media` or `/share`, and include backup/restore policy;
- expose eD2K/Kad peer ports explicitly while keeping EC and amuleapi private;
- use Home Assistant Ingress for the administrative/configuration UI.

Ingress authentication is excellent for administration, according to the
[Home Assistant presentation guide](https://developers.home-assistant.io/docs/apps/presentation/),
but it is not a stable public Stremio transport: Stremio does not possess the
Home Assistant browser session. The manifest, stream and playback routes
therefore require a separate HTTPS origin.

Supported remote-access paths will be:

1. **Recommended:** Cloudflare Tunnel to aMulio's HTTPS origin, with the admin
   UI protected separately and tokenised Stremio routes protected by aMulio.
2. A user-managed reverse proxy with a valid certificate and one forwarded
   HTTPS port.
3. Local-network-only use for Stremio clients on the same network.

Interactive Cloudflare Access cannot protect playback routes because Stremio
cannot complete its login flow. Cloudflare
[service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
also require custom headers that Stremio addons cannot supply. Access may
protect the admin hostname or `/configure`, while manifest/playback routes use
high-entropy revocable aMulio capabilities, rate limits and HTTPS. The
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
connector avoids opening an inbound web port on the Home Assistant host.

## Phase 6 — MVP configuration, branding and localisation

### 6.1 Build the configuration model

- [ ] Define versioned user settings for UI language, preferred result
  languages, quality filters, result limit, maximum size and season packs.
- [ ] Store profiles server-side under random, revocable configuration IDs;
  never put aMule credentials in a manifest URL.
- [ ] Separate read-only Stremio capabilities from an authenticated
  administrator session; possession of a manifest URL must not grant profile
  editing or access to daemon settings.
- [ ] Add create, read, update, rotate and revoke operations with CSRF
  protection and bounded validation.
- [ ] Keep the current instance-level install token migration-compatible.

### 6.2 Replace the prototype configuration page

- [ ] Build a responsive, accessible dark UI with Basic, Search, Language,
  Storage and Advanced sections.
- [ ] Show live aMule EC, eD2K, Kad, Incoming storage and public-URL readiness.
- [ ] Add **Install in Stremio** and **Copy manifest URL** actions with clear
  success/error feedback.
- [ ] Add UI tests for desktop/mobile layouts, keyboard operation, invalid
  settings and install-link generation.

### 6.3 Add official branding and i18n

- [ ] Import the official aMule icon with provenance and per-asset licensing.
- [ ] Serve versioned logo assets and include the logo in the Stremio manifest.
- [ ] Extract every user-facing string into translation resources.
- [ ] Complete English as the default and Spanish as a fully tested locale.
- [ ] Localise status videos or replace embedded text with language-neutral
  visuals plus translated stream descriptions.

**Acceptance:** a new user can configure and install aMulio from a polished
mobile or desktop page; Stremio shows the official aMule logo; a clean browser
defaults entirely to English and switching to Spanish translates the complete
flow.

## Phase 7 — Validate “Download with aMule” end to end

### 7.1 Make remote candidates understandable

- [ ] Use distinct **Ready to play**, **Download with aMule** and
  **Downloading** labels and icons.
- [ ] Present quality, size, language and sources without implying that a
  remote result is already cached.
- [ ] Return a useful empty/error state when eD2K/Kad is disconnected or no
  acceptable candidate exists.

### 7.2 Exercise the real network journey

- [ ] Publish or control a legal small eD2K fixture with known metadata.
- [ ] From Stremio, select the remote fixture and prove one and only one
  download is queued in aMule.
- [ ] Verify status refreshes across queued, downloading, completing and ready
  transitions.
- [ ] Reopen and play the completed file with range requests and seeking.
- [ ] Test cancellation, retry, unavailable sources, daemon restart and stale
  search results.

**Acceptance:** from a fresh aMule instance with an empty Incoming directory, a
user can choose **Download with aMule** in Stremio, observe honest progress and
play the completed legal fixture without touching aMule's UI.

## Phase 8 — Home Assistant app and novice installation

### 8.1 Package the app

- [ ] Create a Home Assistant app repository with `config.yaml`, translated
  options, documentation, changelog, icon/logo and AppArmor profile.
- [ ] Supervise `amuled`, `amuleapi` and aMulio in one least-privileged image.
- [ ] Publish signed `amd64` and `aarch64` images and test fresh install,
  upgrade, rollback and backup restore on Home Assistant OS.
- [ ] Provide conservative storage limits and explain the impact of aMule
  downloads on small Home Assistant devices.

### 8.2 Make remote access guided and safe

- [ ] Provide an Ingress administration UI that generates secrets and reports
  readiness without revealing credentials.
- [ ] Offer an optional Cloudflare Tunnel setup wizard using a user-supplied
  tunnel token; never request a broad Cloudflare API key.
- [ ] Document split protection: Access/HA authentication for administration,
  revocable aMulio bearer capabilities for Stremio routes.
- [ ] Provide an advanced reverse-proxy/port-forwarding guide with TLS, DNS,
  firewall and rotation checks.
- [ ] Add a one-screen copy/install handoff from Home Assistant to Stremio.

**Acceptance:** a Home Assistant OS user can add the repository, install the
app, configure storage, obtain a public HTTPS manifest and play the legal E2E
fixture without SSH, Docker Compose or editing configuration files.

## Phase 9 — Optional progressive `.part` playback experiment

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

The public completed-file E2E is complete. The next work is **Phase 6.1:
versioned configuration profiles**, followed by the configuration UI, official
branding and English-first localisation. Phase 7 must then validate the real
click-to-download journey. Home Assistant packaging follows in Phase 8.
Progressive `.part` playback is deliberately deferred to Phase 9.

CI enforces linting, tests, dependency audits, CodeQL and a coverage floor.

Before changing behavior, run:

```sh
uv run ruff check .
uv run pytest
docker compose --env-file .env.example config
```
