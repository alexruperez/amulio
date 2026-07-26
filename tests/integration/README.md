# Completed-file integration fixture

This fixture compiles the pinned `amule-org/amule` revision with `amuled` and
`amuleapi`, then places a self-produced aMulio MP4 in aMule's Incoming
directory. It never joins an eD2K server or downloads third-party media.

Run it locally with Docker:

```sh
docker compose -f tests/integration/compose.yaml up --build --wait
AMULIO_INTEGRATION_URL=http://127.0.0.1:18000 \
  uv run pytest tests/integration
docker compose -f tests/integration/compose.yaml down --volumes
```

The test waits for aMule to publish `amulio-fixture.mp4`, obtains its eD2K
hash via `amuleapi`, signs a temporary aMulio playback URL, and verifies that
aMulio re-resolves and streams the completed file from the shared read-only
Incoming mount.
