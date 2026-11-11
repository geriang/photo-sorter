# Immich export

Photo Sorter copies photos that contain people and scored Keep into
`output/Sorted/Immich/YYYY/MM/`. Immich reads that folder as a read-only external library,
so its timeline shows only people photos, browsable by year and month.

Originals are never modified. Only copies are written, and `undo --last-run` removes them.

## Export

```
photosorter scan
photosorter faces                          # detect people (InsightFace); score refuses to run before this
photosorter score
photosorter apply --target immich          # dry run: prints counts per year/month, writes nothing
photosorter apply --target immich --yes    # copies files and records a manifest
photosorter undo --last-run                # removes the copies, sidecars and empty folders
```

- Selection is set by `[immich] include_types` and `include_values` (default: `people` and `keep`).
- Folder date order: EXIF date, date in the filename, file modified time, then `Undated/`.
- If a copy had no EXIF date, the resolved date is written into the copy so Immich's timeline matches
  the folders. JPEG gets EXIF. HEIC and PNG get an `<name>.<ext>.xmp` sidecar.
- Two different photos with the same name in one month: the later one gets a short hash suffix.
- `score` is a placeholder until Milestone 4. It marks any photo with a detected face as people and Keep.
  It exits with an error if any photo has not been through `photosorter faces` yet.
- Re-running `scan` keeps earlier face and score results for photos it already knows.
- Export never overwrites an existing file. If an export fails partway, `undo --last-run` still removes
  every file it wrote, and a retry writes each photo once.
- Face detection uses InsightFace (`pip install .[faces]`). It needs a one-off model download.

## Immich setup (Docker on the Mac Studio)

1. Install Immich with its own `docker-compose.yml` and `.env`. Pin `IMMICH_VERSION=v3.3.6` or later
   (not `release`). Release 3.3.6 disables the ONNX Runtime telemetry that older versions send to Microsoft.
2. Copy `scripts/immich/docker-compose.override.yml` next to Immich's compose file.
   Set `PEOPLE_LIBRARY_PATH` in `.env` to the absolute path of `output/Sorted/Immich`.
3. In Immich, add an external library with the import path `/external/people`, then click Scan.
4. Run `python scripts/immich/check_lockdown.py --env /path/to/immich/.env`.

### Read-only mount

The export folder is mounted read-only so Immich can never change your files. Immich cannot write
metadata edits (ratings, tags) back to sidecars on a read-only mount, and those edits fail silently
(Immich issue 10538). Treat the Immich library as view-only.

### Machine learning

- **Default (ML off):** do not start the ML container. In Immich admin settings, turn off
  Machine Learning. You get the year/month timeline of people-only photos. There is no People page.
- **Optional (ML hardened):** start with `--profile ml-hardened`. The ML container runs on an
  `internal` Docker network with no route to the internet, with `ORT_DISABLE_TELEMETRY=1`.
  Models need a one-off download first:
  1. Start the ML container once with `docker-compose.seed.yml` added. This gives it internet access.
  2. Wait for the face models to download into the `model-cache` volume, then stop it.
  3. Start it again without the seed file.

### Model revision (not set)

The override does not set `MACHINE_LEARNING_MODEL_REVISION`. A value of `v2` appears only in the notes
for Immich v3.4 release candidates, and I did not check it against 3.3.6, so it is left out rather than
guessed. If you move to v3.4 or later, check Immich's release notes for the setting before adding it.

### Other outbound traffic from the Immich server

The Immich server is not on the internal network and can reach the internet. In admin settings,
consider turning off the new-version check, map tiles and reverse geocoding. I have not verified
every outbound call Immich can make. To confirm for yourself, watch the containers' network
connections while it runs.

## Why the filter runs before Immich

Immich only detects faces after it has imported a file, so it cannot decide what to import. Photo Sorter
decides which photos have people, and Immich only ever sees that set.

## Not tested

The compose files have not been run through `docker compose config` and no Immich instance has been
started. Run the manual end-to-end check with about 50 photos before the full export.

Also not tested: the read-only mount behaviour (Immich issue 10538) in the latest release, whether any
`MACHINE_LEARNING_MODEL_REVISION` value is needed for v3.3.6 or later, and `photosorter faces` with the
real InsightFace model (the tests use a stub detector).
