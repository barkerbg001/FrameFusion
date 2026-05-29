# FrameFusion Roadmap

## Phase 1 — Core Engine

**Goal:** Upload 10 images, click render, get an MP4.

### Backend

**Repo & app setup** *(done)*

- [x] Monorepo layout — `api/` and `web/` at the root
- [x] FastAPI app structure — `core/`, `models/`, `routers/`, `services/`
- [x] Path config and runtime dirs — `api/uploads/`, `api/output/`

**Project & media API**

- [ ] `POST /project` — create a project (name, aspect ratio, fps, resolution)
- [ ] `POST /project/{id}/media` — upload images/videos to a project
- [ ] `GET /project/{id}/media` — list uploaded media (filename, duration, dimensions)

**Rendering**

- [ ] Basic video renderer — stitch images into video using MoviePy, no audio yet
- [ ] `POST /project/{id}/render` — trigger a render job, return job ID
- [ ] `GET /job/{id}/status` — poll render status (queued / processing / done / failed)
- [ ] `GET /job/{id}/download` — download the finished MP4
- [ ] Output format presets (16:9, 9:16, 1:1) with resolution options

### Frontend

- [ ] Simple file upload area (drag & drop multi-image)
- [ ] Media grid showing uploaded files
- [ ] Render button with job status polling
- [ ] Download link when done
- [ ] No design effort yet — just wiring

---

## Phase 2 — Timeline & Per-Slide Control

**Goal:** User has full control over sequence and timing before rendering.

- [ ] Horizontal timeline component showing each slide as a draggable block
- [ ] Reorder slides via drag & drop
- [ ] Per-slide duration input (default 3s, editable)
- [ ] Global duration setting (apply same duration to all)
- [ ] Delete / duplicate individual slides
- [ ] Slide thumbnail preview in timeline
- [ ] Ken Burns effect toggle per slide (pan left, pan right, zoom in, zoom out)
- [ ] Image fit options per slide (cover / contain / blur background)
- [ ] Backend: accept slide config JSON in render payload

---

## Phase 3 — Audio

**Goal:** Upload images + pick a track + render = a proper video with audio.

- [ ] Upload your own audio track
- [ ] Backend built-in royalty-free music library (10–20 tracks, categorised by mood: lofi, cinematic, upbeat, calm)
- [ ] Music browser UI with play preview
- [ ] Auto-trim audio to match total video duration
- [ ] Global volume control
- [ ] Fade in / fade out toggles
- [ ] Beat sync toggle — auto-adjust slide durations to match audio BPM (use librosa in FastAPI)
- [ ] Multi-track: background music + optional voiceover upload simultaneously

---

## Phase 4 — Text, Overlays & Transitions

**Goal:** Videos look genuinely polished and on-brand.

- [ ] Text overlay editor per slide (add title, subtitle, caption)
- [ ] Font, size, color, alignment, opacity controls
- [ ] Animated text presets (fade in, slide up, typewriter)
- [ ] Logo / watermark upload with position and opacity
- [ ] Progress bar overlay option (renders as bottom strip)
- [ ] Transition selector — apply globally or per slide
- [ ] Transition types: fade, slide, zoom, wipe, glitch (start with 8 solid ones)
- [ ] Image filter per slide: brightness, contrast, saturation, vignette
- [ ] Color grade presets: warm, cool, cinematic, B&W, vintage

---

## Phase 5 — AI Features

**Goal:** User types a prompt and gets a finished video in under 2 minutes.

- [ ] **AI Script Generator** — type a topic, get a voiceover script (Groq/Anthropic API)
- [ ] **AI TTS Voiceover** — convert script to audio via ElevenLabs, auto-attach to project
- [ ] **Auto-subtitles** — transcribe voiceover using Whisper, burn captions into video
- [ ] **AI Image Search** — type a concept, fetch relevant images via Unsplash/Pexels API, add to project in one click
- [ ] **Prompt-to-Video** — type a full concept ("lofi Tokyo study beats"), AI fetches images + picks music + assembles slide config and triggers render
- [ ] **Smart Slide Timing** — AI analyses audio rhythm and suggests slide durations to match energy
- [ ] **AI Thumbnail Generator** — extract best frame + overlay title text, export as PNG

---

## Phase 6 — Projects, Queue & UX

**Goal:** Feels like a real app, not a demo.

- [ ] Named projects with save/load
- [ ] Project dashboard (list view, thumbnails, last edited)
- [ ] Undo/redo stack
- [ ] Duplicate project
- [ ] Batch mode — queue multiple render jobs from different configs
- [ ] Render queue UI with live progress bars
- [ ] Low-res draft preview before final render
- [ ] Auto-save

---

## Phase 7 — Sharing & Publishing

- [ ] Shareable preview link (video streamed from server, no download required)
- [ ] Direct YouTube upload via OAuth
- [ ] Copy embed code
- [ ] QR code generator for sharing
- [ ] Export as GIF option
- [ ] Watermark-free toggle (free vs pro tier groundwork)

---

## Phase 8 — Auth & SaaS Layer (optional)

- [ ] Google OAuth / email auth
- [ ] Per-user project isolation
- [ ] Credit system (free tier = watermark + 480p, pro = 1080p + AI features)
- [ ] Usage dashboard
- [ ] Public API with API key for programmatic access

---

## Build order summary

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
