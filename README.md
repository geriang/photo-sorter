# Photo Sorter

Local-only photo sorting. Scans a folder of photos, computes signals (EXIF, blur, duplicates, faces, Qwen2.5-VL output), scores each photo, and routes copies into `Keep`, `Maybe` or `Toss`. Originals are never modified.

See `../PLAN.md` for the full plan.

## Layout

```
config/               config.example.toml (copy to config.toml)
data/                 local state: db/, thumbnails/, vlm_cache/ (git-ignored)
output/               reports/, manifests/ and the Sorted/ copies (git-ignored)
scripts/              one-off helpers, e.g. the VLM benchmark
docs/                 notes and design decisions
tests/                tests and small fixture images
src/photosorter/
  ingest/             folder scan, hashing, EXIF, filename source detection
  signals/            blur, brightness, perceptual hash, duplicates, event clustering
  vlm/                Ollama client, prompt, JSON schema, cache by file hash
  faces/              face detection, clustering, naming
  scoring/            keep score, type assignment, reason strings
  labeling/           calibration sampling, labels, taste model
  routing/            dry-run, copy to Sorted/, manifest, undo, Toss quarantine
  db/                 SQLite schema and queries
  review/             local web UI (templates/, static/)
```

Milestone 1 starts with `ingest/`, `signals/`, `vlm/` and `db/`.
