# FrameFusion

FrameFusion is a video generation platform for turning still images and audio into long-form videos—built for lofi channels, slideshow content, and short-form clips. It combines a **FastAPI** backend for media processing with a **React + Vite** frontend.

## What exists today

| Area | Status |
|------|--------|
| Lofi video generation API | Working (`POST /api/lofi/generate-video`) |
| Web UI | Lofi creator connected to API |
| Tests, CI, Docker | pytest, Vitest, GitHub Actions, Docker Compose |
| Auth, job queue, cloud storage | Not implemented |

## Features (target)

- **Lofi generator** — Upload one or more images + an audio track; get a 1080p MP4 looped to a target duration (default 60 minutes).
- **Slideshow & shorts** — Cycle images over random or selected music; support portrait (9:16) and landscape (16:9) outputs.
- **Channel workflows** — Organize assets by brand/channel folder and batch-render multiple videos.
- **Web dashboard** — Upload assets, configure renders, track progress, and download results without using curl.

## Architecture

```
FrameFusion/
├── api/          # FastAPI + MoviePy/OpenCV video pipeline
│   ├── app/
│   │   ├── core/       # Config, paths, env
│   │   ├── routers/    # HTTP endpoints
│   │   ├── services/   # Video creation logic
│   │   └── models/     # Pydantic schemas
│   ├── uploads/        # Runtime upload storage (gitignored)
│   └── output/         # Generated videos (gitignored)
└── web/          # React + TypeScript + Vite frontend
```

Processing flow (lofi endpoint):

1. Client uploads images + audio via multipart form.
2. API writes files to a temp directory.
3. `video_creator.create_video_from_images_and_audio()` loops audio to the target length, resizes the first image to 1920×1080, and muxes with MoviePy.
4. API returns the finished MP4 as a file download.

## Prerequisites

- **Python 3.11+** (3.10 may work; test locally)
- **Node.js 20+** and npm
- **FFmpeg 4.4+** on your PATH — required by MoviePy for H.264/AAC encoding (**5.0+** recommended)
- Enough disk space for uploads and rendered output (long lofi videos can be several GB)

### FFmpeg install

FrameFusion uses MoviePy with the `libx264` video and `aac` audio codecs. Verify FFmpeg after install:

```bash
ffmpeg -version
```

Look for `ffmpeg version 4.4` or newer (Debian/Ubuntu packages and Docker images typically ship **5.x** or **6.x**). If `ffmpeg` is missing from PATH, video generation will fail at encode time.

- **Windows:** `winget install Gyan.FFmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add `bin` to PATH.
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg` (Debian/Ubuntu) or equivalent.

## Quick start

### Docker Compose (fastest)

```bash
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080) for the UI or [http://localhost:8000/docs](http://localhost:8000/docs) for the API.

See **[docs/DEPLOY.md](./docs/DEPLOY.md)** for production deployment.

### Local development

#### 1. Backend

```bash
cd api
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Health check: [http://localhost:8000/health](http://localhost:8000/health)

Optional environment variables (copy `api/.env.example` to `api/.env`):

```env
UPLOADS_DIR=./uploads
OUTPUT_DIR=./output
CORS_ORIGINS=http://localhost:5173,http://localhost:8080
```

#### 2. Frontend

```bash
cd web
npm install
npm run dev
```

App: [http://localhost:5173](http://localhost:5173)

In local dev, API requests are proxied to `http://localhost:8000` (see `web/vite.config.ts`). For production builds, copy `web/.env.example` to `web/.env` and set `VITE_API_URL` to your deployed API origin.

The UI includes a **Lofi creator** — upload an image and audio file, set duration, and download the generated MP4.

#### 3. Try the lofi endpoint

```bash
curl -X POST "http://localhost:8000/api/lofi/generate-video" \
  -F "images=@/path/to/image.jpg" \
  -F "audio=@/path/to/track.mp3" \
  -F "output_name=my-lofi.mp4" \
  -F "repeat_minutes=60" \
  --output my-lofi.mp4
```

## API reference

### `GET /health`

Returns API status and configured upload/output paths.

### `POST /api/lofi/generate-video`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `images` | file[] | required | One or more image files (first image is used for the video frame) |
| `audio` | file | required | Audio track (MP3, WAV, etc.) |
| `output_name` | string | `output.mp4` | Output filename |
| `repeat_minutes` | int | `60` | Target video length; audio is looped or trimmed to match |

**Validation:** up to 10 images (`image/*`), max 20 MB each; audio must be `audio/*`, max 100 MB. Returns structured JSON errors:

```json
{
  "error": {
    "code": "file_too_large",
    "message": "Image 1 exceeds maximum size of 20971520 bytes",
    "status": 413
  }
}
```

Codes include `validation_error`, `invalid_media_type`, `empty_file`, `too_many_images`, `file_too_large`, and `internal_error`. Limits are configurable via `MAX_IMAGE_COUNT`, `MAX_IMAGE_SIZE_BYTES`, and `MAX_AUDIO_SIZE_BYTES`.

**Response:** `video/mp4` file download.

### `POST /api/slideshow/generate`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `images` | file[] | required | Images shown evenly across the audio duration |
| `audio` | file | required | Audio track |
| `output_name` | string | `slideshow.mp4` | Output filename |
| `fps` | int | `30` | Frames per second |
| `orientation` | string | `landscape` | `landscape` (1920×1080) or `portrait` (1080×1920) |

**Response:** `video/mp4` file download.

### `POST /api/shorts/generate`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `images` | file[] | required | Images for fast-cut clips |
| `audio` | file | optional | Background audio (trimmed to video length) |
| `output_name` | string | `shorts.mp4` | Output filename |
| `seconds_per_image` | float | `1.0` | Duration per image |
| `orientation` | string | `portrait` | `landscape` or `portrait` |
| `shuffle` | bool | `true` | Randomize image order |
| `max_duration_seconds` | float | — | Optional cap on total length |
| `fps` | int | `30` | Frames per second |

**Response:** `video/mp4` file download.

### `POST /api/batch/channel`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `channel_archive` | file | required | Zip file with one subfolder per video (images inside each subfolder) |
| `brand_name` | string | required | Used for the output zip filename |
| `render_type` | string | `slideshow` | `slideshow` or `shorts` |
| `audio` | file | slideshow only | Shared audio track for slideshow batch renders |
| `orientation` | string | `landscape` | `landscape` or `portrait` |
| `fps` | int | `30` | Frames per second |
| `seconds_per_image` | float | `1.0` | Used for `shorts` batch renders |
| `max_duration_seconds` | float | — | Optional cap for `shorts` batch renders |

**Response:** `application/zip` containing one MP4 per subfolder.

## Development

```bash
# API: install dev tools, lint, type-check, test
cd api
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
mypy app
pytest

# Web: lint, test, build
cd web
npm install
npm run lint
npm test
npm run build
```

Optional: install [pre-commit](https://pre-commit.com/) and run `pre-commit install` from the repo root.

### Project conventions

- Keep HTTP handlers thin; put logic in `api/app/services/`.
- Use Pydantic models in `api/app/models/` for request/response shapes.
- Store runtime media under `api/uploads/` and `api/output/` — never commit generated files.
- Pin Python and Node versions once CI is added (`.python-version`, `engines` in `package.json`).

## Known limitations

- Only the **first uploaded image** is used in the lofi pipeline today.
- Video generation runs **synchronously** in the request — long renders will timeout without a job queue.
- **No authentication** — do not expose the API publicly without adding auth.
- Set **`CORS_ORIGINS`** before production (defaults to `*`).

## Roadmap

See **[ROADMAP.md](./ROADMAP.md)** for a phased plan from the current prototype to a production-ready application.

## License

[MIT](./LICENSE) — Copyright (c) 2023 barkerbg001
