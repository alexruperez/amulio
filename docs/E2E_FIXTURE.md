# Controlled legal eD2K fixture

This runbook prepares the Phase 7.2 end-to-end test without distributing media
or credentials through the repository. It needs two aMule instances: the
ordinary aMulio instance is the downloader, while a second, isolated aMule
instance is the seed. Never use this process with media you are not allowed to
redistribute.

## Current validation status

Live eD2K discovery, selection, queueing and progress reporting have been
validated from Stremio, and cancellation of the test download has been
validated through the aMule control plane. The controlled legal fixture is
prepared, but its completion and playback acceptance remain pending because
the seed must use a public IP different from the downloader.

## Fixture

The supported fixture is **Big Buck Bunny** (`tt1254207`, 2008). Wikimedia
Commons distributes its small source video under CC BY 3.0 and specifies the
attribution `(c) copyright Blender Foundation | www.bigbuckbunny.org`. The
fixture must retain that attribution in the test record and be named:

```text
Big.Buck.Bunny.2008.CC-BY-3.0.aMulio-E2E.mp4
```

The source is approximately 20 MB. aMulio accepts legal short films of at
least 15 MB when no misleading quality label is present; files that claim
`480p` or above still use the normal, much stricter size floors.

Source and licence: [Wikimedia Commons — Big Buck Bunny small.ogv](https://commons.wikimedia.org/wiki/File:Big_Buck_Bunny_small.ogv).

## Isolated seed

Keep the seed separate from the aMulio downloader. It needs its own aMule
configuration, Temp and Incoming volumes, its own EC/amuleapi passwords, and
different peer ports. A real transfer also requires a different public IP:
eD2K clients reject a source that resolves to their own public address, even
when the peer ports differ. Run the seed on a second host for Phase 7.2.
`docker/amuleapi/entrypoint.sh` supports these overrides:

```text
AMULE_TCP_PORT=4663
AMULE_UDP_PORT=4673
AMULE_EC_PORT=4714
AMULE_API_HTTP_PORT=4715
```

Publish only `4663/TCP` and `4673/UDP` for the seed. Keep `4714` and `4715`
private. Add matching host/provider firewall rules temporarily, and remove the
seed and its ports once validation is complete.

Place the transcoded MP4 in the seed's Incoming directory before starting the
seed. Confirm its `shared` API reports the filename, eD2K hash and a completed
source. Preserve the generated eD2K link and licence attribution in a private
test record, not in Git.

### Optional deterministic Stremio bridge

When an eD2K server has not indexed the seed yet, a self-hosted test instance
can opt into a single explicit fixture instead of waiting for discovery. Set
`AMULIO_E2E_FIXTURE_MEDIA_ID` to the Cinemeta movie id and
`AMULIO_E2E_FIXTURE_ED2K_LINK` to that fixture's legal eD2K link. aMulio then
offers only that remote stream for that movie. Both settings default to empty;
they are intended solely for controlled end-to-end tests and should be removed
afterwards.

## Stremio journey

1. Ensure `amuleapi` and eD2K show **Connected** in aMulio. Kad is desirable
   but is not a prerequisite when the fixture's eD2K source is already known.
2. In Stremio search for **Big Buck Bunny** and open the 2008 movie. If the
   active Stremio catalogue does not expose it, temporarily set
   `AMULIO_E2E_FIXTURE_MEDIA_ID` to the IMDb id of another movie you can open.
   This changes only where the legal fixture appears; its filename and eD2K
   source remain Big Buck Bunny. Remove the override after the test.
3. Refresh streams until `Big.Buck.Bunny.2008.CC-BY-3.0.aMulio-E2E.mp4`
   appears as **Download with aMule**. It must be `notWebReady` at this stage.
4. Select it once. Stremio must show the localized “download started” status
   video and aMule must contain exactly one download with the fixture hash.
5. Refresh the title to observe percentage, speed and source count. Once it is
   complete, the stream becomes **Ready to play**.
6. Play it and seek. Confirm normal HTTP range requests return `206`.
7. Exercise cancellation, retry, a seed restart and stale-search recovery.

Record the timestamps, hash, eD2K link, state transitions and any failure. Do
not publish a private installation token, media copy, daemon credentials or
production logs.
