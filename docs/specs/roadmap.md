# Roadmap: Photo Sorter

## Goal
Deliver the full sorter described in `PLAN.md` through Milestone 7. It scans a local folder of about 4,000 still photos, computes signals (EXIF, blur, duplicates, faces, Qwen2.5-VL output), scores each photo, and routes copies to `Keep`, `Maybe` or `Toss`. A person reviews and corrects the result in a local web UI, and the taste model learns from those corrections. The Immich people export (Milestone 8, already built on `agent/immich-export`) is merged first and must keep working in every later phase.

**Done for the whole effort** means all of these are true:
- Every phase below is merged, `main` is green (`pytest` 0 failed), and nothing from a later phase leaked into an earlier PR.
- On the user's real library (checked on the Mac Studio, a Manual (user) step): fewer than 1 in 100 memories land in Toss, the Maybe pile is under about 20% of the library, and the taste model agrees with at least 80% of about 20 held-out labels. These are the targets in `PLAN.md` and are measured in Phase 17.
- `undo --last-run` removes every copy a run made, and the originals are byte-identical to before (hash check).

**Constraints that hold in every phase:**
- Originals are never modified. Output is copies only, and every write can be undone.
- No network calls except to the local Ollama endpoint. Models are pulled by the user, never by the app at run time.
- No private data in the repo. Thumbnails, VLM output, labels and manifests stay git-ignored. Tests use generated images only.
- Each phase is one reviewable PR, mergeable on its own, and leaves `main` working. Anything that needs the user's Mac is marked "Manual (user)" with a clear step.

**Reject a phase PR if:** it breaks `main` or a passing test; it states something nobody ran; or it contains work from a later phase.

## Phases

### Phase 1: Immich slice fix and merge
- **Deliverable:** the 9 failing regression tests pass, `photosorter faces` exists, re-scan keeps results, export and undo are crash-safe, and the docs and plan are corrected. Detailed in `docs/specs/plan-readiness.md`.
- **Verify:** the full `pytest` run shows 0 failed. The scan, faces, score, apply and undo workflow works in a temp dir. Manual (user): the 50-photo Immich check.
- **Depends on:** nothing.
- **Branch:** `agent/immich-export` (the existing branch, an exception to the naming rule because it already has 8 commits).

### Phase 2: Quality signals and metadata
- **Deliverable:** `scan` also records blur (Laplacian variance), brightness, overexposure, image dimensions, camera model, front or rear camera, GPS, and a `source` of camera, screenshot or download from the filename and EXIF. Adds OpenCV and a safe schema upgrade that keeps existing rows.
- **Verify:** unit tests on generated images (a blurred copy scores lower than a sharp one). A re-scan of a populated database keeps all earlier columns.
- **Depends on:** Phase 1.
- **Branch:** `agent/phase-2-quality-signals`

### Phase 3: Duplicates
- **Deliverable:** a perceptual hash for each photo, `duplicate_group_id` and `is_best_in_group`, and a `duplicates` command that groups near-identical photos.
- **Verify:** tests with generated near-duplicates (resized, re-compressed) land in one group, and unrelated images do not. The best-in-group pick is stable across runs.
- **Depends on:** Phase 2 (uses its quality score to pick the best copy).
- **Branch:** `agent/phase-3-duplicates`

### Phase 4: Ollama client and VLM cache
- **Deliverable:** a local Ollama client with the structured JSON schema from `PLAN.md`. Images are resized to about 1024 px before sending. Results are cached by file hash. A `vlm` command processes a given list of photos. The endpoint is restricted to localhost.
- **Verify:** tests with a fake HTTP server check the schema validation, the cache hit (no second call) and the refusal of a non-local endpoint. Manual (user): `ollama pull qwen2.5vl:7b`, then run `vlm` on 3 photos.
- **Depends on:** Phase 1.
- **Branch:** `agent/phase-4-vlm-client`

### Phase 5: VLM benchmark and contact sheet
- **Deliverable:** a benchmark script that runs 32B against 7B on the same 20 photos and reports seconds per photo and agreement with the user's own type and ephemeral labels. Also an HTML contact sheet that shows each photo with its signals and VLM output. This closes Milestone 1.
- **Verify:** the contact sheet builds from generated fixtures and needs no network. Manual (user): run the benchmark on the Mac, spot-check 30 photos on the sheet, then record the chosen model in `config.toml`.
- **Depends on:** Phases 2, 3 and 4.
- **Branch:** `agent/phase-5-benchmark-contact-sheet`

### Phase 6: Full VLM pass
- **Deliverable:** a resumable run of the VLM across the whole library, with progress, a stop and resume that never repeats cached photos, and a per-run time estimate.
- **Verify:** a test interrupts a run partway and the resume makes no repeated calls. Manual (user): an overnight run on about 4,000 photos finishes, and the cache covers every file.
- **Depends on:** Phase 5 (model choice).
- **Branch:** `agent/phase-6-full-vlm-pass`

### Phase 7: Event clustering
- **Deliverable:** `event_id`, `event_size` and `in_trip_cluster`, computed from time and GPS, and an `events` command.
- **Verify:** tests with generated timestamps and coordinates form the expected clusters. Photos with no date or GPS get no event and do not crash.
- **Depends on:** Phase 2 (GPS and date).
- **Branch:** `agent/phase-7-events`

### Phase 8: Face embeddings and clustering
- **Deliverable:** stored face embeddings (InsightFace) and unnamed face clusters, with `people_count` and `group_size`. The faces from Phase 1 are reused, and there is no UI yet.
- **Verify:** tests with a stub embedder group the expected clusters. Manual (user): run on the 50-photo test folder and check the cluster count looks sensible.
- **Depends on:** Phase 1.
- **Branch:** `agent/phase-8-face-clusters`

### Phase 9: Review app shell and People screen
- **Deliverable:** the first FastAPI app on `localhost` with plain HTML/JS, and the People screen. Typing a name once applies it to a whole cluster and stores `person:<name>`, `rel:*` and `selfie` tags.
- **Verify:** API tests with a test client check that naming a cluster tags every photo in it. The server binds to 127.0.0.1 only. Manual (user): open the screen and name two clusters.
- **Depends on:** Phase 8.
- **Branch:** `agent/phase-9-people-screen`

### Phase 10: Default scoring and reasons
- **Deliverable:** the hand-weighted keep score replaces the placeholder. It sets the type (people, moment, document, screenshot, misc), the value zones (0.7 and 0.3) and a readable reason string. The Immich export keeps working with the new score.
- **Verify:** table-driven tests (blurry duplicate gives toss with a reason that names the original, an ephemeral screenshot, a people photo). The Immich export tests still pass.
- **Depends on:** Phases 2, 3, 6, 7 and 8.
- **Branch:** `agent/phase-10-default-scoring`

### Phase 11: Run report screen and sorted dry-run
- **Deliverable:** `apply --dry-run` for the `Keep/Memories/{People,Moments}`, `Keep/Reference`, `Maybe` and `Toss` folders, plus the Run report screen with counts per folder. It writes nothing.
- **Verify:** a test checks that a dry run leaves the output folder empty and the counts match the database. The screen loads from the test client.
- **Depends on:** Phases 9 and 10.
- **Branch:** `agent/phase-11-run-report`

### Phase 12: Calibration screen and labels
- **Deliverable:** a stratified sample of about 100 photos and the Calibrate screen with the keys K, M, T and Z (undo). Labels are stored by file hash.
- **Verify:** tests check that the sample covers each type and score band, that Z reverts the last label, and that labels survive a re-scan. Manual (user): label 100 photos.
- **Depends on:** Phases 9 and 10.
- **Branch:** `agent/phase-12-calibration`

### Phase 13: Taste model
- **Deliverable:** train a small model (logistic regression or decision tree) on the labels, hold out about 20, and report the agreement rate. Use hand weights until enough labels exist, and show the model's reason next to the guess.
- **Verify:** tests with generated labels show that training is repeatable and that fewer labels than the minimum fall back to the hand weights. Manual (user): the agreement rate on real labels is reported (target 80% or more).
- **Depends on:** Phase 12.
- **Branch:** `agent/phase-13-taste-model`

### Phase 14: Real routing and undo
- **Deliverable:** `apply --yes` copies photos into the Sorted folders with a manifest. `undo --last-run` generalizes the Immich logic to all targets. Never overwrites, never touches originals.
- **Verify:** tests carried over from the Immich slice (crash-safe, no overwrite, refuses unsafe paths). A hash check shows the originals are unchanged after apply and undo.
- **Depends on:** Phases 1 and 11.
- **Branch:** `agent/phase-14-real-routing`

### Phase 15: Review grid and Toss quarantine
- **Deliverable:** the Review grid screen (Maybe and Toss, multi-select, move to Keep or Toss, reason on each card), and the Toss quarantine with 30-day expiry. Expired files go to the OS trash only after the user confirms.
- **Verify:** tests with a fake clock check that nothing is removed before 30 days and that nothing is removed without confirmation. Moves are recorded in the manifest and are undoable.
- **Depends on:** Phase 14.
- **Branch:** `agent/phase-15-review-grid-quarantine`

### Phase 16: Feedback loop and active learning
- **Deliverable:** corrections from the Review grid become labels and the model retrains. The Calibrate screen asks only about the least-certain photos.
- **Verify:** tests show a correction creates a label and changes the next prediction. The uncertainty ranking picks the expected photos on a generated set.
- **Depends on:** Phases 13 and 15.
- **Branch:** `agent/phase-16-feedback-loop`

### Phase 17: Library view, search, watch mode and success check
- **Deliverable:** the Library view (browse by type, tag, event or year, with a search box over VLM descriptions), watch mode for new photos, and a `report` command that computes the three success measures (Toss memories, Maybe share, held-out agreement). This closes Milestone 7.
- **Verify:** tests for search and for watch mode picking up a new generated file. Manual (user): the report on the real library meets the three targets, or the gap is written down.
- **Depends on:** Phases 15 and 16.
- **Branch:** `agent/phase-17-library-success-check`

## Status
| Phase | Name | Status |
|---|---|---|
| 1 | Immich slice fix and merge | Spec written (`docs/specs/plan-readiness.md`), awaiting approval. Not implemented and not merged: `origin/main` has only the initial commit and PR #1, and `agent/immich-export` has 8 local commits ahead of `main`, no PR and no pushed branch. The spec has no Progress log or Deviations yet. |
| 2 | Quality signals and metadata | Not started |
| 3 | Duplicates | Not started |
| 4 | Ollama client and VLM cache | Not started |
| 5 | VLM benchmark and contact sheet | Not started |
| 6 | Full VLM pass | Not started |
| 7 | Event clustering | Not started |
| 8 | Face embeddings and clustering | Not started |
| 9 | Review app shell and People screen | Not started |
| 10 | Default scoring and reasons | Not started |
| 11 | Run report screen and sorted dry-run | Not started |
| 12 | Calibration screen and labels | Not started |
| 13 | Taste model | Not started |
| 14 | Real routing and undo | Not started |
| 15 | Review grid and Toss quarantine | Not started |
| 16 | Feedback loop and active learning | Not started |
| 17 | Library view, search, watch mode and success check | Not started |

## Assumptions
- Only still photos (JPEG, PNG, HEIC). Video, RAW and Live Photos are out of scope.
- Hardware, as reported by the user: Mac Studio M5, 128 GB RAM. `qwen2.5vl:32b` is pulled. `qwen2.5vl:7b` is not, and the user must pull it before Phase 5.
- Dry-run by default applies to every command that writes, as `PLAN.md` states under Safety. The user did not list it among the roadmap-wide constraints, so a phase may keep it simple but must not remove it.
- Phase 3 follows Phase 2 because it uses the quality score. Phases 7 and 8 can be done in either order.
- Milestone 8 (Immich export) is Phase 1. Later phases only have to keep its tests passing.
- The photo folder path is still unknown. It is needed from Phase 2 onward for any manual check, and it goes in the git-ignored `config/config.toml` only.
- The roadmap has 17 phases because each one is sized for a single reviewable PR of about 5 to 8 tasks. Phases 12 and 13 can be merged if the first turns out small.
