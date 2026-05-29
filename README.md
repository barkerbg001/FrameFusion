# FrameFusion

**FrameFusion** is a Python-based video generator that creates videos using image folders and audio clips. It includes a FastAPI backend and a React frontend to streamline usage across various video styles.

## 📁 Project Structure

```
FrameFusion/
├── api/               # FastAPI backend
│   ├── app/
│   │   ├── core/      # Config and shared settings
│   │   ├── models/    # Pydantic schemas
│   │   ├── routers/   # API route handlers
│   │   ├── services/  # Business logic (rendering, etc.)
│   │   └── main.py    # App entrypoint
│   ├── uploads/       # Uploaded media (created at runtime, gitignored)
│   ├── output/        # Rendered videos (created at runtime, gitignored)
│   └── requirements.txt
└── web/               # React frontend (Vite)
```

## 🎬 Features

- Generate videos from images and audio
- Available API endpoints:
  - `/lofi` – Lofi-style loop
  - `/shorts` – Vertical short-form
  - `/video` – Standard format
  - `/youtube` – YouTube-ready format
- React UI for managing and triggering jobs

## 🔧 Setup

### 1. Backend (FastAPI)

Install dependencies (from inside the `api` folder):

```bash
cd api
pip install -r requirements.txt
```

Run the API (from inside the `api` folder):

```bash
uvicorn app.main:app --reload
```

### 2. Frontend (React)

Inside the `web` folder:

```bash
cd ../web
npm install
npm run dev
```

## 🔁 Endpoints

| Method | Endpoint                      | Description              |
|--------|-------------------------------|--------------------------|
| GET    | `/health`                     | API health check         |
| POST   | `/api/lofi/generate-video`    | Generate lofi loop video |
| GET    | `/api/youtube/download-video` | Download YouTube video   |

## 🗺️ Roadmap

Phased roadmap ordered by what builds on what.

### Phase 1 — Core Engine (The Foundation)

Get something that actually works end to end before any UI polish.

#### Backend (FastAPI)

- [x] Project scaffolding with clean folder structure (`api/`, `web/`)
- [ ] `POST /project` — create a project with name, aspect ratio, fps, resolution
- [ ] `POST /project/{id}/media` — upload images/videos to a project
- [ ] `GET /project/{id}/media` — list uploaded media with metadata (filename, duration, dimensions)
- [ ] Basic video renderer — stitch images into video using MoviePy, no audio yet
- [ ] `POST /project/{id}/render` — trigger a render job, return job ID
- [ ] `GET /job/{id}/status` — poll render status (queued / processing / done / failed)
- [ ] `GET /job/{id}/download` — download the finished MP4
- [ ] Output format presets baked in (16:9, 9:16, 1:1) with resolution options

#### Frontend (React)

- [ ] Simple file upload area (drag & drop multi-image)
- [ ] Media grid showing uploaded files
- [ ] Render button with job status polling
- [ ] Download link when done
- [ ] No design effort yet — just wiring

**Goal:** Upload 10 images, click render, get an MP4. That's it.

### Phase 2 — Timeline & Per-Slide Control

Give users actual control over the video structure.

- [ ] Horizontal timeline component showing each slide as a draggable block
- [ ] Reorder slides via drag & drop
- [ ] Per-slide duration input (default 3s, editable)
- [ ] Global duration setting (apply same duration to all)
- [ ] Delete / duplicate individual slides
- [ ] Slide thumbnail preview in timeline
- [ ] Ken Burns effect toggle per slide (pan left, pan right, zoom in, zoom out)
- [ ] Image fit options per slide (cover / contain / blur background)
- [ ] Backend: accept slide config JSON in render payload

**Goal:** User has full control over sequence and timing before rendering.

### Phase 3 — Audio

The feature that makes it actually feel like a video.

- [ ] Upload your own audio track
- [ ] Backend built-in royalty-free music library (10–20 tracks, categorised by mood: lofi, cinematic, upbeat, calm)
- [ ] Music browser UI with play preview
- [ ] Auto-trim audio to match total video duration
- [ ] Global volume control
- [ ] Fade in / fade out toggles
- [ ] Beat sync toggle — auto-adjust slide durations to match audio BPM (use librosa in FastAPI)
- [ ] Multi-track: background music + optional voiceover upload simultaneously

**Goal:** Upload images + pick a track + render = a proper video with audio.

### Phase 4 — Text, Overlays & Transitions

Visual polish that separates it from a basic slideshow.

- [ ] Text overlay editor per slide (add title, subtitle, caption)
- [ ] Font, size, color, alignment, opacity controls
- [ ] Animated text presets (fade in, slide up, typewriter)
- [ ] Logo / watermark upload with position and opacity
- [ ] Progress bar overlay option (renders as bottom strip)
- [ ] Transition selector — apply globally or per slide
- [ ] Transition types: fade, slide, zoom, wipe, glitch (start with 8 solid ones)
- [ ] Image filter per slide: brightness, contrast, saturation, vignette
- [ ] Color grade presets: warm, cool, cinematic, B&W, vintage

**Goal:** Videos look genuinely polished and on-brand.

### Phase 5 — AI Features

The differentiator. This is where FrameFusion becomes more than a slideshow tool.

- [ ] **AI Script Generator** — type a topic, get a voiceover script (Groq/Anthropic API)
- [ ] **AI TTS Voiceover** — convert script to audio via ElevenLabs, auto-attach to project
- [ ] **Auto-subtitles** — transcribe voiceover using Whisper, burn captions into video
- [ ] **AI Image Search** — type a concept, fetch relevant images via Unsplash/Pexels API, add to project in one click
- [ ] **Prompt-to-Video** — type a full concept ("lofi Tokyo study beats"), AI fetches images + picks music + assembles slide config and triggers render
- [ ] **Smart Slide Timing** — AI analyses audio rhythm and suggests slide durations to match energy
- [ ] **AI Thumbnail Generator** — extract best frame + overlay title text, export as PNG

**Goal:** User types a prompt and gets a finished video in under 2 minutes.

### Phase 6 — Projects, Queue & UX

Make it production-ready for real use.

- [ ] Named projects with save/load
- [ ] Project dashboard (list view, thumbnails, last edited)
- [ ] Undo/redo stack
- [ ] Duplicate project
- [ ] Batch mode — queue multiple render jobs from different configs
- [ ] Render queue UI with live progress bars
- [ ] Low-res draft preview before final render
- [ ] Auto-save

**Goal:** Feels like a real app, not a demo.

### Phase 7 — Sharing & Publishing

Get the output out into the world.

- [ ] Shareable preview link (video streamed from server, no download required)
- [ ] Direct YouTube upload via OAuth
- [ ] Copy embed code
- [ ] QR code generator for sharing
- [ ] Export as GIF option
- [ ] Watermark-free toggle (free vs pro tier groundwork)

### Phase 8 — Auth & SaaS Layer (optional, if you want to go public)

- [ ] Google OAuth / email auth
- [ ] Per-user project isolation
- [ ] Credit system (free tier = watermark + 480p, pro = 1080p + AI features)
- [ ] Usage dashboard
- [ ] Public API with API key for programmatic access

### Build Order Summary

| Phase | Focus | Delivers |
|-------|-------|----------|
| 1 | Core engine | Images → MP4 |
| 2 | Timeline control | Sequencing & timing |
| 3 | Audio | Music + beat sync |
| 4 | Text & transitions | Polished output |
| 5 | AI features | The differentiator |
| 6 | Projects & queue | Real app UX |
| 7 | Sharing | Distribution |
| 8 | Auth & SaaS | Monetisation |

## 📄 License

MIT License — free to use and modify.
