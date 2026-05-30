# FrameFusion Roadmap

This document is the master checklist for taking FrameFusion from its current prototype state to a complete, shippable product. Work through phases in order where possible; later phases can overlap once foundations are stable.

**Legend:** `[x]` done · `[~]` partial · `[ ]` not started

---

## Current state (baseline)

- [x] FastAPI app skeleton with CORS and lifespan hooks
- [x] Lofi video service (`create_video_from_images_and_audio`)
- [x] `POST /api/lofi/generate-video` endpoint
- [x] Configurable uploads/output directories
- [x] React + Vite + TypeScript frontend scaffold
- [x] Dependabot for npm and pip
- [x] Root README (this file's companion)
- [x] Frontend connected to API
- [x] Tests, CI, Docker, deployment

---

## Phase 1 — Backend stabilization

Goal: reliable API core that you can call from any client.

### 1.1 Fix and harden existing endpoints

- [x] Add input validation: file size limits, allowed MIME types (image/*, audio/*), max image count
- [x] Return structured errors (`422` validation, `413` too large, `500` with safe messages)
- [x] Add request logging (correlation id, duration, output size)

### 1.2 Consolidate video services

- [x] Implement video services in `api/app/services/`:
  - [x] `slideshow.py` — multi-image + single audio, evenly timed frames
  - [x] `shorts.py` — fast-cut portrait/landscape clips
  - [x] `channel_batch.py` — scan folder tree and batch render
- [x] Stop writing temp files to CWD — `video_creator` uses `tempfile`
- [x] Unify on MoviePy 2.x API (audit deprecated `.set_duration`, `.set_audio`, etc.)

### 1.3 New API routes

- [x] `POST /api/slideshow/generate` — images + audio + options (fps, resolution, orientation)
- [x] `POST /api/shorts/generate` — images + optional audio + duration cap
- [x] `POST /api/batch/channel` — brand name + folder structure + render type
- [x] `GET /api/jobs/{id}` — job status (after Phase 2 queue)
- [x] `GET /api/jobs/{id}/download` — fetch completed file

### 1.4 Configuration and dependencies

- [x] Add `api/.env.example` with all supported variables
- [x] Pin versions in `requirements.txt` (e.g. `fastapi==0.115.x`)
- [x] Add missing deps: `pydantic-settings`, `python-magic` or `filetype`, `Pillow`, `requests`
- [x] Document FFmpeg version requirement in README

### 1.5 Security basics

- [x] Restrict CORS to frontend origin(s) via env (`CORS_ORIGINS`)
- [x] Sanitize filenames (no path traversal in `output_name`)
- [x] Rate limiting on expensive endpoints (e.g. `slowapi` or reverse proxy)

**Phase 1 exit criteria:** All endpoints return correct responses; no legacy scripts required for core flows; OpenAPI docs accurate.

---

## Phase 2 — Async jobs and storage

Goal: long renders (60+ min lofi) do not block HTTP workers or time out.

### 2.1 Job queue

- [x] Choose queue backend: **Redis + Celery**, **RQ**, or **ARQ** (lighter) — **ARQ** with inline fallback for dev/CI
- [x] Job model: `id`, `status` (queued/running/completed/failed), `progress`, `created_at`, `output_path`, `error`
- [x] Change generate endpoints to `202 Accepted` + `{ job_id }` instead of synchronous file response
- [x] Worker process: `arq app.worker.settings.WorkerSettings` (or inline queue locally)
- [x] Progress callbacks during MoviePy encode (where supported)

### 2.2 Storage

- [x] Persist job metadata (SQLite for dev, Postgres for prod)
- [x] TTL cleanup for old uploads and outputs (cron or scheduled task)
- [x] Optional S3-compatible storage (MinIO locally, S3/R2 in prod) for multi-instance deploys

### 2.3 Webhooks (optional)

- [x] `POST /api/jobs/{id}/webhook` config — notify client when render completes

**Phase 2 exit criteria:** 60-minute lofi render can be queued from API and polled to completion without gateway timeout.

---

## Phase 3 — Frontend application

Goal: usable product UI replacing the Vite starter page.

### 3.1 Foundation

- [x] Rename package from `frontend` to `framefusion-web`
- [x] Add router (`react-router`), UI kit (shadcn/ui or similar), HTTP client (`fetch` wrapper or axios)
- [x] Env: `VITE_API_URL=http://localhost:8000`
- [x] Vite dev proxy to API (optional, for cookie auth later)

### 3.2 Core pages

- [x] **Home / dashboard** — recent jobs, quick actions
- [x] **Lofi creator** — drag-and-drop image + audio, duration slider, submit → download (sync; job progress in Phase 2)
- [x] **Slideshow creator** — multi-image upload, reorder, preview timing
- [x] **Shorts creator** — aspect ratio toggle (9:16 / 16:9), clip length
- [~] **Job detail** — status, progress, webhook, download link (retry deferred)
- [x] **Settings** — default output name, quality presets

### 3.3 UX polish

- [x] Upload progress indicators
- [x] Error toasts with API error messages
- [x] Responsive layout (mobile-friendly uploads)
- [x] Dark theme fitting “lofi” aesthetic
- [x] Optional: image thumbnail grid
- [ ] Optional: audio waveform preview

**Phase 3 exit criteria:** Full lofi workflow completable in browser without curl; job status visible for async renders. ✅

---

## Phase 4 — Quality, testing, and DevOps

Goal: confidence to ship and accept contributions.

### 4.1 Testing

- [x] **API unit tests** — pytest for `video_creator` (FFmpeg smoke test in CI)
- [x] **API integration tests** — TestClient with generated fixture assets
- [x] **Frontend tests** — Vitest + React Testing Library for App/API status
- [x] **E2E** — Playwright: upload → wait for job → download (CI with mocked or fast 5s render)

### 4.2 CI/CD

- [x] GitHub Actions workflow:
  - [x] `api`: install deps, ruff, mypy, pytest
  - [x] `web`: npm ci, lint, build, test
- [x] Fail PR on lint/test errors
- [x] Optional: build Docker images on `main`

### 4.3 Containerization

- [x] `api/Dockerfile` — Python slim + FFmpeg
- [x] `web/Dockerfile` — multi-stage build → nginx static
- [x] `docker-compose.yml` — api + web + redis + worker
- [x] Document `docker compose up` in README and `docs/DEPLOY.md`

### 4.4 Code quality

- [x] `pyproject.toml` — ruff, mypy, pytest config
- [x] Pre-commit hooks (format, lint)
- [x] Strict TypeScript (`strict: true` already; add API response types/codegen from OpenAPI)

**Phase 4 exit criteria:** Green CI on every PR; one-command local stack via Docker Compose.

---

## Phase 5 — Production readiness

Goal: safe, observable deployment for real users.

### 5.1 Authentication and authorization

- [ ] User accounts (email/OAuth) or API keys for programmatic access
- [ ] Per-user upload quotas and job limits
- [ ] Private job outputs — users can only access their own files

### 5.2 Deployment

- [x] Docker Compose local/production stack documented in `docs/DEPLOY.md`
- [ ] Choose hosting: e.g. Railway, Fly.io, AWS ECS, or VPS + Docker
- [ ] Separate worker tier from API tier
- [ ] HTTPS, reverse proxy (Caddy/nginx), gzip
- [ ] Environment-specific config (staging vs production)

### 5.3 Observability

- [ ] Structured logging (JSON)
- [ ] Metrics: queue depth, render duration, failure rate
- [ ] Error tracking (Sentry)
- [ ] Health checks for load balancer (`/health` + worker/redis connectivity)

### 5.4 Legal and product

- [ ] Terms of service / acceptable use (user-supplied media rights)
- [ ] Privacy policy if storing user uploads in cloud

**Phase 5 exit criteria:** Deployed staging environment; authenticated user can create and download a video end-to-end.

---

## Phase 6 — Advanced features (post-MVP)

Pick based on product direction; not required for “full project” v1.

### 6.1 Richer video pipeline

- [ ] Multi-image lofi with crossfade or Ken Burns motion
- [ ] Text overlays (title, timestamp, “live” badge)
- [ ] Video filters (grain, vignette, color grade presets)
- [ ] Ambient loop video layer over still background
- [ ] Normalize audio loudness (EBU R128 / `-14 LUFS` target)

### 6.2 Integrations

- [ ] Stock image/audio libraries (Unsplash, local royalty-free packs)
- [ ] Template presets (“Rainy window lofi”, “Study beats 24/7”)

### 6.3 Collaboration

- [ ] Teams / shared workspaces
- [ ] Asset library per channel (reuse uploads)
- [ ] Scheduled renders (cron-style “publish every Monday”)

### 6.4 Performance

- [ ] GPU encoding (NVENC) when available
- [ ] Render preview at low resolution before full export
- [ ] Chunked/resumable uploads for large audio files

---

## Suggested timeline (solo developer)

| Phase | Focus | Rough effort |
|-------|--------|--------------|
| 1 | Backend stabilization | 1–2 weeks |
| 2 | Job queue + storage | 1–2 weeks |
| 3 | Frontend | 2–3 weeks |
| 4 | Tests + Docker + CI | 1 week |
| 5 | Auth + deploy | 1–2 weeks |
| 6 | Advanced features | ongoing |

Total to **shippable v1**: about **6–10 weeks** part-time, depending on scope cuts.

---

## Recommended v1 scope (cut list)

To ship faster, defer these until after v1:

- Multi-user teams
- GPU encoding

**v1 must-haves:**

1. Lofi + slideshow + shorts generation via API  
2. Async jobs with progress polling  
3. Web UI for upload and download  
4. Docker Compose + CI  
5. Basic auth or API keys + CORS lockdown  

---

## Immediate next steps (this week)

1. Pin `requirements.txt` versions  
2. TTL cleanup for old job workspaces and outputs

---

## Tracking

Update checkboxes in this file as work completes. Link PRs in commit messages or a changelog when you start releasing versions (`v0.1.0`, `v1.0.0`).
