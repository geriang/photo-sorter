# Plan readiness review and Immich-slice fixes

## Goal
Judge whether `PLAN.md` is ready for implementation, then close the gaps that can be fixed now. The Immich slice (Milestone 8, built early on `agent/immich-export`) must pass its own regression tests. The plan and docs must match what the code does and what has actually been verified.

Verdict from the review:

| Part of the plan | Ready? | Why |
|---|---|---|
| Decisions table, goal, safety rules | Yes | Clear and consistent. The photos are stills only. |
| Milestone 1 (signals + VLM benchmark) | Yes, with one user step | Hardware is known: Mac Studio M5, 128 GB RAM, which is plenty for `qwen2.5vl:32b` (21 GB). `ollama list` shows `qwen2.5vl:32b` is pulled but `qwen2.5vl:7b` is not, so the 32B vs 7B benchmark needs `ollama pull qwen2.5vl:7b` first. Not started in code. |
| Milestones 2 to 7 | Planned, not specced | Split into Phases 2 to 17 in `docs/specs/roadmap.md`. This spec is Phase 1 of that roadmap. Success criteria are not yet measurable (see Tasks). |
| Milestone 8 (Immich export) | Not ready to merge | 9 of 33 tests fail (see below). Docs are missing the `faces` step. The override has one unverified setting. |

Current test state, run in this container with `pip install --target /tmp/opencode/deps` and `PYTHONPATH=/tmp/opencode/deps:src python3 -m pytest -q`: 24 pass, 9 fail. All 9 are in the untracked `tests/test_regressions.py`.

## Scope
- Make all 9 failing regression tests pass without weakening them.
- Add the `photosorter faces` command and make `score` refuse to run before faces are detected.
- Fix re-scan, export failure handling, filename collisions and undo safety.
- Fix only the proven gaps in `PLAN.md`, `docs/immich.md` and the compose override.
- Work on the existing branch `agent/immich-export`.

## Acceptance criteria
1. **AC1.** `PYTHONPATH=/tmp/opencode/deps:src python3 -m pytest -q -p no:cacheprovider` reports 34 passed, 0 failed (the 33 existing tests plus the one new test from AC5b). The count is not lowered and no test is deleted or skipped.
2. **AC2.** The CLI workflow `scan`, `faces`, `score`, `apply --target immich --yes`, `undo --last-run` works in a temp dir with the stub detector (`test_cli_workflow_exports_people_without_manual_db_edits`). `score` before `faces` exits 1 and prints a message containing `faces` on stderr (`test_score_refuses_when_faces_have_not_been_detected`).
3. **AC3.** If an export fails partway, `undo --last-run` from a fresh DB connection removes every file the run wrote. A retry afterwards writes each photo exactly once (`test_failed_export_*`).
4. **AC4.** Export never overwrites an existing file, including a file that sits at the hash-suffixed candidate name, and names that differ only by case do not collide (`test_foreign_files_*`, `test_names_differing_only_by_case_*`).
5. **AC5.** `undo` checks every manifest row before deleting anything. If one row is unsafe (outside the export dir, a symlink out, or an original photo), it raises `ValueError`, deletes nothing and leaves the run open (`test_undo_*`).
5b. **AC5b.** After an export and an undo, the original photos are byte-identical to before (sha256 of every file under the source folder, compared before and after). This carries the roadmap-wide rule that originals are never modified. Check it with a new test in `tests/test_regressions.py` that snapshots the source folder around `apply --yes` and `undo --last-run`.
6. **AC6.** Re-running `scan` keeps `has_people`, `group_size`, `type`, `value`, `score` and `reason` for photos that are already known (`test_rescan_keeps_detection_and_scoring`).
7. **AC7.** `docs/immich.md` lists `photosorter faces` in the workflow. `scripts/immich/docker-compose.override.yml` no longer sets `MACHINE_LEARNING_MODEL_REVISION`, and the docs say why (see Assumptions). `PLAN.md` states which milestones exist in code, and its success criteria are measurable. `grep -n MODEL_REVISION scripts/immich/docker-compose.override.yml` finds nothing. Every unverified claim appears under "Not tested".
8. **AC8. Manual (user).** On the Mac Studio, export about 50 photos with `photosorter apply --target immich --yes`, add `output/Sorted/Immich` as an external library in Immich, and check three things. Immich shows only people photos. Its timeline matches the Year/Month folders. `python scripts/immich/check_lockdown.py --env <immich .env>` exits 0 and `docker compose ... config` accepts the override. Also look at the ML container's network connections while it runs.

## Out of scope
- Milestones 1 to 7: no VLM client, benchmark, blur/duplicate signals, review UI, taste model or Toss quarantine.
- Resolving how `Keep/Memories/...` relates to `Sorted/Immich/` (left for Phases 11 and 14 of the roadmap).
- Anything from roadmap Phases 2 to 17. A change that belongs to a later phase is scope creep and gets rejected.
- Running Docker, Immich or Ollama (AC8 is the user's check). Pulling `qwen2.5vl:7b` is also a user step, for Milestone 1.
- Changing the stray "Agent test" line in `README.md`, the `datetime.utcfromtimestamp` deprecation in `ingest/scan.py`, or any remote or repo setting.
- Handling video, RAW or Live Photos (the user says the library is stills only).

## Approach
1. **Re-scan:** replace `INSERT OR REPLACE` in `ingest/scan.py` with an upsert that updates `path`, `size`, `format`, `exif_date` and `mtime` and keeps the other columns.
2. **Faces command:** add `faces` to `cli.py` with a module-level `load_detector()` (lazy InsightFace import, so tests can monkeypatch it) that calls `detect_people`. `score` exits 1 with an error mentioning `faces` if any photo has `has_people IS NULL`. The existing `tests/test_cli.py` sets `has_people` by hand and must still pass.
3. **Export safety:** commit the `runs` row before copying. Record and commit a manifest row for each copy so that any file on disk is covered. If a copy or `_write_date` fails, remove that item's partial copy and do not record it, then re-raise. Create files exclusively (`open(..., "xb")` or equivalent) instead of `shutil.copy2` over an existing path.
4. **Collisions:** compare targets with `casefold()` for the `claimed` set and for existing files. When the plain name is taken, try the `_<hash8>` suffix, then longer or numbered suffixes, until a free name is found. Check disk existence for every candidate.
5. **Undo:** two phases. First resolve and validate all rows: inside the export dir, not a symlink out, and not equal to any manifest `source` or `photos.path`. Raise `ValueError` before deleting anything. Then delete files and prune empty folders. Mark `undone` only after phase 2 succeeds.
6. **Docs and plan:** make the edits listed in the Tasks.

Edge cases to cover: an item that fails on the first or the last position, a foreign file at both candidate names, an undo target that is itself in `photos`, and an undo run twice.

## Files likely touched
- `src/photosorter/ingest/scan.py`
- `src/photosorter/cli.py`
- `src/photosorter/routing/immich.py`
- `src/photosorter/scoring/default.py` (only if the faces check is placed there)
- `tests/test_regressions.py` (commit it; only fix real test bugs, and say so in the PR)
- `tests/test_cli.py` (only if needed)
- `docs/immich.md`
- `scripts/immich/docker-compose.override.yml`
- `PLAN.md`
- `README.md` (workflow line, if it mentions the commands)
- `docs/specs/plan-readiness.md`

## Tasks
- [x] 1. Create the test environment and record the baseline (24 pass, 9 fail). Verify: the pytest command from AC1 shows `9 failed, 24 passed`. Serves AC1.
- [x] 2. Make `scan` keep earlier results. Verify: `pytest tests/test_regressions.py -k rescan` passes. Serves AC6.
- [x] 3. Add the `faces` command and the `score` guard. Verify: `pytest tests/test_regressions.py -k "cli_workflow or refuses"` and `pytest tests/test_cli.py` pass. Serves AC2.
- [x] 4. Make export crash-safe and non-overwriting, with case-insensitive collision handling. Verify: `pytest tests/test_regressions.py -k "failed_export or foreign or case"` and `tests/test_immich_export.py` pass. Serves AC3, AC4.
- [x] 5. Make undo two-phase and refuse originals. Verify: `pytest tests/test_regressions.py -k undo` passes. Serves AC5.
- [x] 5b. Add the test that proves the originals are unchanged after apply and undo. Verify: `pytest tests/test_regressions.py -k originals_unchanged` passes. Serves AC5b.
- [ ] 6. Fix `docs/immich.md` and the override: add the `faces` step, remove `MACHINE_LEARNING_MODEL_REVISION`, add a note that `v2` is documented only for v3.4 release candidates and was not checked for 3.3.6, and keep the "Not tested" section accurate. Verify: `grep -n MODEL_REVISION scripts/immich/docker-compose.override.yml` finds nothing, and `pytest tests/test_check_lockdown.py` passes. Serves AC7.
- [ ] 7. Update `PLAN.md` with only proven gaps:
  - a status column marking Milestone 8 as built early and Milestone 1 as not started;
  - the stills-only answer, the hardware (Mac Studio M5, 128 GB RAM) and the Ollama state, with those questions removed from "Remaining questions". Ollama state: `qwen2.5vl:32b` is pulled (21 GB), `qwen2.5vl:7b` is not, and the benchmark step must say to run `ollama pull qwen2.5vl:7b`. The other pulled models (`nemotron-3-super:120b`, `qwen3.5:122b`, `gpt-oss:120b`, `qwen3.8:27b`, `qwen2.5:72b`) are not used by the plan, and no claim is made about whether they accept images;
  - the one remaining open question, the photo folder path;
  - success metrics given a way to measure them (for example, "memories in Toss" is counted on the labeled set from calibration), with a pointer to `docs/specs/roadmap.md` as the phase order, where Phase 17 computes the three measures;
  - Milestone 8 "done when" marked as a manual check.

  Verify: `git diff main -- PLAN.md` shows only these changes. Serves AC7.
- [ ] 8. Run the full suite, check `git status` and `git diff origin/main...HEAD`, then open the PR with the reviewer's findings. Verify: the AC1 command shows 34 passed, and only the files above changed. Serves AC1 to AC7. AC8 is handed to the user in the PR body.

## Test plan
- Automated: the full pytest suite (34 tests: 33 existing plus the new originals-unchanged test). All fixtures use generated images in `tmp_path`, so no real photos are used.
- The face detector is stubbed (`StubDetector`). InsightFace is not installed or run.
- Manual (user): AC8, plus `docker compose config` on the override. Neither was run here.

## Assumptions
- The user wants the work on `agent/immich-export` and no new branch. There is no open PR for it yet.
- The photo library has stills only (JPEG, PNG, HEIC), matching `IMAGE_SUFFIXES`.
- The `faces` and `score` design is the one the regression tests describe.
- `MACHINE_LEARNING_MODEL_REVISION=v2` is removed because it was only found in the v3.4 release candidate notes. The same notes list the 3.3.6 telemetry fix. Immich v3.4.0 was released 10 Nov 2026. The pin of `v3.3.6` or later in `check_lockdown.py` stays.
- The read-only-mount claim in `docs/immich.md` matches Immich issue 10538. That issue is still open and was read online this session. Behavior in the latest release was not re-tested.
- Python 3.11 is available. In this container `python3 -m venv` fails (no ensurepip), so tests run with `PYTHONPATH=/tmp/opencode/deps:src`.
- Reported by the user, not checked by me: Mac Studio M5 with 128 GB RAM, and this `ollama list` output: `nemotron-3-super:120b`, `qwen3.5:122b`, `gpt-oss:120b`, `qwen3.8:27b`, `qwen2.5vl:32b`, `qwen2.5:72b`. `config.example.toml` already uses `qwen2.5vl:32b` and `qwen2.5vl:7b`, so no code change follows from this.
- Still open for the user (not blocking this PR): the photo folder path. It must be a folder that already contains photos, because it is read-only input. For AC8, use a separate test folder holding copies of about 50 photos, not the full library. The app creates `output/Sorted/` itself. Set the path as `paths.source` in `config/config.toml`, which is git-ignored. Do not put the path or any photos in the repo or in chat.

## Risks
- Switching export from `copy2` to exclusive create must keep file times (`copy2` semantics). Check `tests/test_immich_export.py` for this.
- Per-item commits make export slower on large runs. This is acceptable at about 4,000 photos.
- An undo that refuses on any bad row can block undo of a good run. This is deliberate: nothing is deleted if anything looks wrong.
- The Immich lockdown claims stay unverified until AC8 is done.
- `tests/test_regressions.py` was written by an earlier agent. Fix the code first and change a test only if it is really wrong.

## Proposed branch name
`agent/immich-export` (existing branch, 8 commits ahead of `main`, no PR yet)

## Deviations
- Task 4: `StubDetector` in `tests/conftest.py` (not listed under Files likely touched) was case-sensitive, so `PERSON_a.JPG` had no people and `test_names_differing_only_by_case_*` could never see a collision. Fixed the stub to match "person" in any case; the test itself is unchanged. User approved this via the question tool.

## Progress log
- Task 1: baseline confirmed with the AC1 command: `9 failed, 24 passed`. Commit: see `git log` ("Add spec and regression tests; record baseline").
- Task 2: upsert in `scan.py`; `pytest -k rescan` 1 passed.
- Task 3: `faces` command, `load_detector()` and `score` guard in `cli.py`; `-k "cli_workflow or refuses"` 2 passed, `tests/test_cli.py` 2 passed.
- Task 4: `_Namer`, exclusive create, manifest-first commit and cleanup in `routing/immich.py`, plus the stub fix above. `-k "failed_export or foreign or case"` and `tests/test_immich_export.py` pass (see below).
- Task 5: two-phase `undo_last` (validates every row, refuses symlinks and originals, marks undone last). `-k undo` 5 passed. Tasks 4 and 5 were written together in one file and share one commit.
- Task 5b: `test_originals_unchanged_after_apply_and_undo` passes; it fails when export is temporarily mutated to write into the source (mutation not committed).
