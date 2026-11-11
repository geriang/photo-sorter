# Photo Sorter: Project Plan (v2)

## Decisions so far
| Question | Answer | Effect on the design |
|---|---|---|
| Where are the photos? | Local drive on a Mac Studio | Ingest is a folder scan. No cloud sync needed. |
| How many? | About 4,000+ | Small enough to run a vision model on every photo. |
| Processing | Local only, Qwen2.5-VL available | No cloud calls. Qwen2.5-VL is the main "understanding" model. |
| Interface | Simple visual review UI | A small local web app, not CLI-only. |
| "Friends" | Too narrow. Any photo with people | Replaced by a `people` type. Relationship is a tag, not a folder. |
| Model size | Qwen2.5-VL 32B for now; 7B may be good enough | Benchmark both in Milestone 1 and pick on speed vs accuracy. Model name is a config value. |
| Photo source | Ordinary folders (not the macOS Photos library) | Plain folder scan. No Photos-library handling needed. |
| Selfies | Merge into People | One `People` folder. `selfie` becomes a tag. |
| Originals | Copy only | Originals are never moved or modified. Organized copies go in a separate output folder. |
| Runtime | Ollama (not MLX or LM Studio) | The app calls Ollama's local HTTP API (`localhost:11434`). |
| Disk space | Plenty free | Full copies are fine. No need for hard links. |
| File types | Still photos only (JPEG, PNG, HEIC) | No video, RAW or Live Photo handling. |
| Hardware | Mac Studio M5, 128 GB RAM (reported by the user, not checked) | Plenty for `qwen2.5vl:32b` (21 GB). |
| Ollama models | `qwen2.5vl:32b` is pulled (21 GB). `qwen2.5vl:7b` is not | Run `ollama pull qwen2.5vl:7b` before the 32B vs 7B benchmark. The other pulled models (`nemotron-3-super:120b`, `qwen3.5:122b`, `gpt-oss:120b`, `qwen3.8:27b`, `qwen2.5:72b`) are not used by this plan, and I make no claim about whether they accept images. |

## Goal
Scan the photo library, compute signals for each image, score how worth keeping it is, and route it to `Keep`, `Maybe` or `Toss`. Nothing is deleted automatically, and everything can be undone.

## Core design
- Every image gets two independent labels:
  - **Type:** what is in it (people, moment, document, screenshot, ...).
  - **Value:** will I want it later (`keep`, `maybe`, `toss`).
- **Layer 1, signals:** cheap classical checks (EXIF, blur, duplicates) plus Qwen2.5-VL for understanding.
- **Layer 2, taste model:** a small model (logistic regression or a small decision tree) trained on about 100 of your Keep/Maybe/Toss labels.
- Hand-set default weights are used until enough labels exist.

## Type tags (replacing the old primary tags)

| Type | Meaning | Folder |
|---|---|---|
| `people` | Any photo with one or more people (selfies, friends, family, groups, strangers at an event) | Keep/Memories/People |
| `moment` | Travel, scenery, food, pets, events with no people | Keep/Memories/Moments |
| `document` | Paper, ID, receipt, whiteboard, form | Keep/Reference (if durable) |
| `screenshot` | Screen capture | Depends on value |
| `misc` | A real photo that fits nowhere else | Depends on value |

**Why `people`:** it's one folder for any photo with people in it. The relationship goes in secondary tags such as `person:Anna`, `rel:family`, `rel:friend` and `group_size:5`. You can then build views like "all family photos" or "photos with Anna" without a folder per relationship.

Other names, if you prefer: `Together`, `Faces`, `People_Moments`.

**Selfies:** they live in `People`. `selfie` is a secondary tag (front camera, close framing, one or two faces), so you can still filter for them in the Library view.

## Folders
```
Keep/
├── Memories/
│   ├── People/
│   └── Moments/
└── Reference/        (documents, receipts, IDs)
Maybe/                (review queue)
Toss/                 (quarantine; 30 days, then OS trash on your confirmation)
```

## Value zones
- score above 0.7: Keep
- 0.3 to 0.7: Maybe
- score below 0.3: Toss (strict; when unsure, choose Maybe)

## Signals

**Classical (fast, run on every photo):**
| Group | Signals |
|---|---|
| File | sha256, perceptual hash, size, dimensions, format (including HEIC) |
| Metadata | EXIF date, GPS, camera model, front/rear camera, filename pattern, `source` (camera / screenshot / download) |
| Quality | blur (Laplacian variance), brightness, overexposure |
| Duplicates | duplicate_group_id, is_best_in_group |
| Context | event_id, event_size, in_trip_cluster (time + GPS) |

**Qwen2.5-VL (one structured call per photo, returns JSON):**
| Field | Example |
|---|---|
| `type_guess` | people / moment / document / screenshot / misc (plus an `is_selfie` flag) |
| `people_count` | 0, 1, 2, 5+ (also counts people whose faces aren't visible) |
| `scene` | beach, restaurant, office, street, indoor |
| `text_summary` | what the visible text is, in one line |
| `text_kind` | receipt, id, chat, boarding_pass, otp, whiteboard, meme, none |
| `is_ephemeral` | true for OTPs, "driver arriving", parking spots, wifi passwords |
| `quality_note` | accidental, pocket shot, finger over lens, blank |
| `description` | one sentence, used for search |
| `confidence` | 0 to 1 |

Faces are handled separately by a face library (InsightFace) so that named people (`person:<name>`) are consistent. The VLM doesn't identify people.

## Using the local model on 4,000 photos
- Qwen2.5-VL can replace a separate OCR engine, since it reads text well. Tesseract can be kept as an optional fast pre-filter.
- Run the VLM **once per photo** and cache the result by file hash, so re-runs are free. Resize images to about 1024px before sending to keep it fast.
- Speed depends on the model size and runtime. I don't know yet what your Mac Studio does, so **Milestone 1 includes a benchmark** on 20 photos. As a guess, a few seconds per photo means a few hours for the whole library, which is fine as an overnight run. If it's too slow, drop to a smaller variant or run the VLM only on photos the classical checks can't decide.
- Serve it through Ollama. The app talks to it over a local HTTP endpoint, so the runtime and model can be swapped in config.
- The benchmark compares **32B vs 7B** on the same 20 photos: seconds per photo, and how often each agrees with your own judgement of type and ephemeral text. The 32B is the default until the numbers say otherwise.

## Pipeline
Ingest -> metadata -> quality -> duplicates -> faces -> VLM -> event clustering -> score -> route -> log

## Visual review UI (simple, local)
A small web app that runs on `localhost`. It is not a cloud service and nothing leaves the machine.

**Stack:** FastAPI backend and plain HTML/JS (or htmx). I'm avoiding Streamlit and Gradio because they make single-key labeling awkward.

**Screens:**
1. **Calibrate:** one large photo, the app's guess and its reason, and keys **K** (keep), **M** (maybe), **T** (toss), **Z** (undo last). Shows progress, for example "37 / 100".
2. **Review grid:** thumbnails of Maybe and Toss, with multi-select and "move to Keep / Toss". Each card shows its reason string.
3. **People:** clusters of unknown faces. Type a name once, then it applies to the whole cluster.
4. **Library:** browse by type, tag, event or year, with a search box over the VLM descriptions.
5. **Run report:** what `apply --dry-run` would do, with counts per folder, before you confirm.

## Tech stack
Python, SQLite, Pillow + pillow-heif, piexif, OpenCV, imagehash, InsightFace, Qwen2.5-VL (via Ollama), scikit-learn, FastAPI.

## Safety
- Dry-run is the default.
- Copy only. Originals stay where they are, untouched. Organized copies go to a separate `Sorted/` output folder, and a manifest records source -> copy so `undo` can remove the copies.
- Disk use: copies roughly double the library size. You have plenty of free space, so this is fine.
- `undo --last-run` (also available as a button in the UI).
- Local-only: no network calls except to the local model endpoint.
- Every decision stores a readable reason, e.g. "toss: blurry + duplicate of IMG_0412".

## Build order

Status as of this edit. The phase order and the per-phase checks are in `docs/specs/roadmap.md`.

| Milestone | Status |
|---|---|
| 1. Signals and VLM benchmark | Not started. Only the scan and hashing parts exist, as part of Milestone 8. |
| 2. Full VLM pass and context | Not started |
| 3. People | Not started. A minimal `faces` command (face count only) was pulled forward for Milestone 8. |
| 4. Default scoring and dry-run | Not started. A placeholder `score` was pulled forward for Milestone 8. |
| 5. Calibration UI | Not started |
| 6. Real routing | Not started |
| 7. Feedback loop and polish | Not started |
| 8. Immich export | Built early, on branch `agent/immich-export`. Automated tests pass. The "done when" check below is manual and has not been run. |

### Milestone 1: Signals and VLM benchmark (first deliverable)
- Scaffold, SQLite schema, `scan` command.
- Ingest + hashing, EXIF and filename source detection, HEIC support.
- Blur, brightness, perceptual hash, duplicate groups.
- VLM call with the JSON schema above, tested on 20 photos with both 32B and 7B for speed and accuracy. First run `ollama pull qwen2.5vl:7b`, because only the 32B is pulled.
- Output: signals table plus an HTML contact sheet showing each photo and its signals.
- **Done when:** the contact sheet looks right on 30 spot-checked photos and the VLM speed is known.

### Milestone 2: Full VLM pass and context
- Run the VLM across all 4,000 photos (resumable, cached by hash).
- Event clustering by time + GPS.

### Milestone 3: People
- Face detection and clustering, naming UI, `person:<name>` and `rel:*` tags.
- Route `people`, with `selfie` as a tag.

### Milestone 4: Default scoring and dry-run
- Hand-weighted keep score, type assignment, reason strings.
- `apply --dry-run` report screen.

### Milestone 5: Calibration UI
- Pick about 100 varied photos (stratified by type and score), show the guess.
- Keyboard labeling. Labels stored with the file hash.
- Train the taste model, hold out about 20 labels, report the agreement rate.

### Milestone 6: Real routing
- Copy to folders, undo log, Toss quarantine with 30-day expiry.

### Milestone 7: Feedback loop and polish
- Corrections become labels and the model retrains.
- Active learning: ask only about the least-certain photos.
- Watch mode for new photos, search by tag.

### Milestone 8: Immich export
- `apply --target immich`: copies photos with type `people` and value `keep` to `Sorted/Immich/YYYY/MM/`.
- Date order: EXIF, filename, file modified time, `Undated/`. Undated copies get the date written into the copy (EXIF for JPEG, XMP sidecar for HEIC/PNG).
- Manifest, dry-run by default, `undo --last-run`.
- `scripts/immich/`: compose override (ML off by default, opt-in hardened profile with no internet access and telemetry off) and `check_lockdown.py`.
- Face detection (Milestone 3) and default scoring (Milestone 4) are pulled forward in minimal form. `score` is a placeholder.
- **Done when (manual check by the user, not yet run):** about 50 photos show only people photos in Immich, the timeline matches the Year/Month folders, and no outbound connection is seen from the Immich ML container.
- See `docs/immich.md`.

## Success criteria
Each one is measured on the user's real library, by a `report` command planned for Phase 17 of `docs/specs/roadmap.md`. The numbers come from the labels made in the Calibrate screen.
- **Memories in Toss:** fewer than 1 in 100. Counted on the labeled set: of the photos the user labeled Keep, the share the app routed to Toss.
- **Maybe pile:** under about 20% of the library after calibration. Counted as photos in Maybe divided by all photos.
- **Taste model agreement:** at least 80% on about 20 held-out labels. Counted as held-out labels where the model's value equals the user's label.

## Remaining questions
1. What is the path of the photo folder (on the local drive)? Are there subfolders to skip? It goes in `paths.source` in the git-ignored `config/config.toml`.
