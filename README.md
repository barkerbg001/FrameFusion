# FrameFusion

FrameFusion is a monorepo for AI-assisted short-form video creation. The **FastAPI**
backend in `api/` powers specialist agents and video tools. The **Vite + TypeScript**
frontend in `web/` provides **Framey** — the chat UI for research, scripting, b-roll
montages, narration, and rendered MP4s.

## Features

- **Framey chat** — conversational agent with tool calling (research, video, Pexels)
- **9:16 vertical videos** — text shorts, narrated shorts, b-roll montages
- **Pexels b-roll pipeline** — download clips, stitch montages, add narration
- **Specialist agents** — researcher, screenwriter, video editor, music composer, idea generator
- **Data tools** — weather, Pokemon, Wikipedia, Pexels, time
- **Web media library** — browse all generated videos in one place
- **Local chat history** — conversations saved in the browser; delete anytime

## Project structure

```text
FrameFusion/
|-- api/
|   |-- app/
|   |   |-- agents/          # Framey (director), researcher, screenwriter, editor, …
|   |   |-- models/
|   |   |-- routers/
|   |   `-- services/
|   |-- generated/           # Rendered MP4s (gitignored)
|   |-- requirements.txt
|   `-- .env
|-- web/
|   |-- src/
|   |   |-- chat.ts          # Framey UI
|   |   |-- chatStorage.ts   # localStorage chat persistence
|   |   `-- mediaLibrary.ts  # Media gallery
|   `-- package.json
|-- LICENSE
|-- package.json           # root commands: npm run dev, setup, …
|-- scripts/
|   |-- run-api.mjs
|   `-- setup-api.mjs
`-- README.md
```

## Requirements

### API

- Python 3.10+
- FFmpeg (used by MoviePy)
- API keys (see below)

### Web

- Node.js 20+
- npm

## Setup

From the **repo root**:

```powershell
npm install
npm run setup
```

That installs web dependencies, creates `api/.venv`, and installs Python packages.

### API (manual)

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `api/.env`:

```dotenv
GEMINI_API_KEY=your_gemini_key
PEXELS_API_KEY=your_pexels_key
ELEVENLABS_API_KEY=your_elevenlabs_key

# Optional
ELEVENLABS_VOICE_ID=your_voice_id
ELEVENLABS_MUSIC_MODEL=music_v2
MUSIC_PROVIDER=elevenlabs
GEMINI_MODEL=gemini-2.5-flash
```

| Key | Required for |
| --- | --- |
| `GEMINI_API_KEY` | Framey chat and all Gemini agents |
| `PEXELS_API_KEY` | Pexels search, b-roll download, backgrounds |
| `ELEVENLABS_API_KEY` | Narrated shorts, voiceover, and AI music (falls back to free procedural music without it) |
| `MUSIC_PROVIDER` | Optional: `elevenlabs` or `procedural` (auto-detects from API key if unset) |

The `.env` file is gitignored. Do not commit secrets.

### Web

```powershell
cd web
npm install
```

## Run

From the **repo root** (recommended):

```powershell
npm install          # once — installs root tooling + run scripts
npm run setup        # once — web deps + api venv + pip packages
npm run dev          # API + web together
```

| Command | What it does |
| --- | --- |
| `npm run dev` | API (port 8000) + web (port 5173) |
| `npm run dev:api` | API only, with reload |
| `npm run dev:web` | Web only |
| `npm run start:api` | API without reload |
| `npm run build` | Production web build |
| `npm run setup` | Install web + create `api/.venv` + pip deps |

- App: http://127.0.0.1:5173 (proxies `/api` to the backend)
- API: http://127.0.0.1:8000
- Swagger: http://127.0.0.1:8000/docs

The API runner uses `api/.venv` when present, otherwise system `python`.

### Manual (per folder)

**API** (from `api/`):

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Web** (from `web/`):

```powershell
npm run dev
```

## Web app

### Framey chat

Talk to Framey to research topics, create text/narrated shorts, or build Pexels b-roll
montages with optional voiceover. Videos appear inline in the chat and in the **Media**
library.

Example prompts:

- *Research Pikachu with verified facts for a short video*
- *Create a narrated short about Claude AI skills*
- *Create a motivational b-roll montage for a Pokemon video*

### Chat history

Conversations are stored in **localStorage** (`framefusion:chats`) in your browser.
Use the **⋮** menu on any chat in **Recents** to **Rename** or **Delete** it. Renamed
titles are kept even as the conversation grows.

### Media library

Open **Media** in the sidebar to see every MP4 Framey created — merged from chat
attachments and the server's `api/generated/` folder.

## Agent architecture

FrameFusion is moving toward a **production studio** model. Each role has a
specialist agent; Framey (chat) coordinates them for fast tasks, while
`POST /api/agents/production` runs the full crew.

```
🎬 Director Agent      — creative vision, assigns specialists, final approval
📋 Producer Agent      — workflow, deadlines, asset tracking
🔍 Research Agent      — facts, references, source material
✍️ Script Agent        — hooks, storytelling, script writing
📷 Cinematography Agent — shot lists, camera movement, composition
🎨 Visual Agent        — b-roll direction, visual style, asset plan
🎤 Voice Agent         — narration plan, voice selection, delivery
🎼 Music Director Agent — mood per scene, music prompts, transitions
🔊 Sound Design Agent  — SFX, ambient layers, mix notes
✂️ Editor Agent        — assembly, timing, cuts, render
🎞️ Render Agent        — fast script-to-MP4 (legacy produce-short)
```

**Full production pipeline** (`POST /api/agents/production`):

```
Director → Producer → Research → Script → Cinematography → Visual
  → Voice → Music Director → Sound Design → Editor → MP4
```

The **Editor** reads cinematography (shot list + clip timing), visual (Pexels
queries + palette), voice (narrated vs silent), and music director (score +
mux). B-roll briefs cut a multi-clip montage; narrated briefs use the visual
plan for background and typography.

**Framey chat** (fast path — tools + selective fallbacks):

```
Research: weather, Pokemon, Wikipedia, time, Pexels search
Video: text short, sound short
Footage: download Pexels clips, stitch montage (+ auto music)
Music: generate background music (ElevenLabs or free fallback)
Audio: add narration or audio file to existing video
```

**Legacy quick pipeline** (`POST /api/agents/director`):

```
Research → Script → Editor → MP4
```

### B-roll montage (chat tools)

```
download_pexels_footage → stitch_pexels_footage → generate_music → add_audio (automatic for silent b-roll)
```

Silent b-roll requests (e.g. "generate a Tokyo b-roll video") get subtle instrumental
background music by default. Say **silent** or **no music** to skip it.

## API endpoints

### Chat & media

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/chat/health` | Health check |
| `POST` | `/api/chat` | Talk to Framey |
| `GET` | `/api/chat/videos` | List generated MP4s |
| `GET` | `/api/chat/videos/{filename}` | Download/stream a video |
| `GET` | `/api/chat/audio/{filename}` | Download/stream generated music |

### Agents

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/agents/registry` | List all production studio agents |
| `POST` | `/api/agents/production` | Full studio pipeline (all specialists) |
| `POST` | `/api/agents/director-brief` | Director creative vision + assignments |
| `POST` | `/api/agents/workflow` | Producer workflow plan |
| `POST` | `/api/agents/cinematography` | Shot list and composition |
| `POST` | `/api/agents/visual` | Visual style and asset plan |
| `POST` | `/api/agents/voice` | Narration and delivery plan |
| `POST` | `/api/agents/music-director` | Scene music cues and prompts |
| `POST` | `/api/agents/sound-design` | SFX and mix suggestions |
| `POST` | `/api/agents/director` | Legacy research → script → edit pipeline |
| `POST` | `/api/agents/research` | Unified research report |
| `POST` | `/api/agents/screenwrite` | Short-form script |
| `POST` | `/api/agents/edit-video` | Edit and render a video |
| `POST` | `/api/agents/compose-music` | Generate background music (execution) |
| `POST` | `/api/agents/produce-short` | Render from script (Render Agent) |
| `POST` | `/api/agents/ideas` | Brainstorm short-form ideas |

### Video & data tools

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/shorts/generate-text-video` | Silent 9:16 text video |
| `POST` | `/api/shorts/generate-sound-video` | ElevenLabs narrated video |
| `POST` | `/api/shorts/generate-audio-video` | Video from uploaded audio |
| `POST` | `/api/lofi/generate-video` | Lofi loop from image + audio |
| `GET` | `/api/pokemon/{identifier}` | Pokemon data (PokeAPI) |
| `GET` | `/api/weather?location=` | Current weather (Open-Meteo) |
| `GET` | `/api/time?timezone=` | Current time (IANA timezone) |
| `GET` | `/api/wikipedia/search?query=` | Wikipedia extracts + citations |
| `GET` | `/api/pexels/search?query=` | Pexels photos/videos |

## Example: director pipeline

`POST /api/agents/director`

```json
{
  "task": "Create a weather briefing short about Johannesburg this week",
  "context": "Upbeat tone for commuters",
  "produce_short": true,
  "short_format": "auto"
}
```

Returns research, script, and optional rendered video with Pexels background.

## Example: text video

`POST /api/shorts/generate-text-video`

```json
{
  "text": "Sometimes the smallest step changes everything.",
  "duration_seconds": 10,
  "background_color": "#264653",
  "text_color": "#FFFFFF",
  "font_size": 96,
  "output_name": "quote.mp4"
}
```

Output is `1080x1920` at 30 FPS. Omit `background_color` for a random palette color.

## Notes

- Generated MP4s live in `api/generated/` and persist until manually removed.
- Chat history is browser-local only — not synced across devices.
- Output filenames must end in `.mp4` and cannot contain path separators.
- Colors use `#RRGGBB` format.
- External APIs (Gemini, Pexels, ElevenLabs) have their own rate limits and billing.

## License

FrameFusion is available under the [MIT License](LICENSE).

## Tags

Use these consistently so issues, PRs, and the GitHub repo stay easy to filter.

### GitHub repository topics

`ai` `video-editing` `short-form-video` `generative-ai` `fastapi` `python` `typescript` `vite` `gemini` `elevenlabs` `pexels` `b-roll` `monorepo`

### PR and issue labels

| Label | Use for |
| --- | --- |
| `api` | Backend, routers, services, Python deps |
| `web` | Frontend, chat UI, media library |
| `agents` | Director, producer, editor, music, research, etc. |
| `video` | Rendering, MoviePy, FFmpeg, Pexels footage |
| `audio` | Music, narration, sound design, ElevenLabs |
| `docs` | README, comments, API docs |
| `deps` | Dependabot, npm, pip, root scripts |
| `bug` | Something broken |
| `enhancement` | New feature or improvement |

Create matching labels in **Issues → Labels** if they do not exist yet.

### Commit scopes (optional)

Prefix commits with an area when it helps:

```text
api: add music director endpoint
web: audio player in chat attachments
agents: wire editor to cinematography plan
docs: update setup instructions
deps: bump vite in web
```

Common scopes: `api`, `web`, `agents`, `video`, `audio`, `docs`, `deps`, `scripts`.
