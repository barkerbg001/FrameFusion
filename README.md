# FrameFusion

AI-assisted short-form video creation. **Framey** (chat UI in `web/`) talks to a
**FastAPI** backend (`api/`) that runs specialist agents, Pexels b-roll tools, music
generation, and MP4 rendering.

## Quick start

**Prerequisites:** Python 3.10+, Node.js 20+, FFmpeg, npm

```powershell
git clone https://github.com/your-org/FrameFusion.git
cd FrameFusion
npm install
npm run setup
```

Create `api/.env` (see [Configuration](#configuration)), then:

```powershell
npm run dev
```

| URL | Purpose |
| --- | --- |
| http://127.0.0.1:5173 | Web app (Framey chat) |
| http://127.0.0.1:8000/docs | API (Swagger) |

| Command | What it does |
| --- | --- |
| `npm run dev` | API + web together |
| `npm run dev:api` | API only (with reload) |
| `npm run dev:web` | Web only |
| `npm run start:api` | API without reload |
| `npm run build` | Production web build |
| `npm run setup` | Web deps + `api/.venv` + pip install (incl. dev tools) |
| `npm run test:api` | Run API pytest suite |
| `npm run lint:api` | Ruff lint on `api/app` and `api/tests` |
| `npm run format:api` | Ruff format on `api/app` and `api/tests` |
| `npm run typecheck:api` | Mypy on `api/app` |

The API runner uses `api/.venv` when present, otherwise system `python`.

<details>
<summary>Manual setup (without root scripts)</summary>

**API** — from `api/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Production / minimal runtime only: `pip install -r requirements.txt`

**Web** — from `web/`:

```powershell
npm install
npm run dev
```

</details>

## Configuration

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
| `ELEVENLABS_API_KEY` | Narrated shorts, voiceover, and AI music (free procedural fallback without it) |
| `MUSIC_PROVIDER` | Optional: `elevenlabs` or `procedural` |

The `.env` file is gitignored. Do not commit secrets.

## Using Framey

Open http://127.0.0.1:5173 and chat with **Framey** to research topics, create
text or narrated shorts, or build Pexels b-roll montages. Videos appear inline and
in the **Media** sidebar.

**Example prompts**

- *Research Pikachu with verified facts for a short video*
- *Create a narrated short about Claude AI skills*
- *Generate a Tokyo b-roll video*

**Chat history** — stored in browser `localStorage` (`framefusion:chats`). Use the
**⋮** menu on any chat to rename or delete it.

**Media library** — sidebar **Media** tab lists every MP4 from chat attachments and
`api/generated/`.

**B-roll + music** — silent b-roll montages get background music automatically.
Say *silent* or *no music* to skip it.

## Architecture

FrameFusion uses a **production studio** model: specialist agents plan and render
each part of a short. Framey (chat) uses a fast tool path; `POST /api/agents/production`
runs the full crew.

### Agents

| Agent | Role |
| --- | --- |
| 🎬 Director | Creative vision, assigns specialists, final approval |
| 📋 Producer | Workflow, deadlines, asset tracking |
| 🔍 Research | Facts, references, source material |
| ✍️ Script | Hooks, storytelling, script writing |
| 📷 Cinematography | Shot lists, camera movement, composition |
| 🎨 Visual | B-roll direction, visual style, asset plan |
| 🎤 Voice | Narration plan, voice selection, delivery |
| 🎼 Music Director | Mood per scene, music prompts, transitions |
| 🔊 Sound Design | SFX, ambient layers, mix notes |
| ✂️ Editor | Assembly, timing, cuts, render |
| 🎞️ Render | Fast script-to-MP4 (`produce-short`) |

### Pipelines

**Full production** — `POST /api/agents/production`

```text
Director → Producer → Research → Script → Cinematography → Visual
  → Voice → Music Director → Sound Design → Editor → MP4
```

The Editor uses cinematography (shot timing), visual (Pexels + palette), voice
(narrated vs silent), and music director (score + mux).

**Framey chat** — tools and fallbacks for quick tasks

```text
Research → text/sound short | Pexels download → stitch → music → mux
```

**Legacy** — `POST /api/agents/director`

```text
Research → Script → Editor → MP4
```

## API reference

### Chat & media

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/chat/health` | Health check |
| `POST` | `/api/chat` | Talk to Framey |
| `GET` | `/api/chat/videos` | List generated MP4s |
| `GET` | `/api/chat/videos/{filename}` | Stream/download a video |
| `GET` | `/api/chat/audio/{filename}` | Stream/download music |

### Agents

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/agents/registry` | List production studio agents |
| `POST` | `/api/agents/production` | Full studio pipeline |
| `POST` | `/api/agents/director-brief` | Director vision + assignments |
| `POST` | `/api/agents/workflow` | Producer workflow plan |
| `POST` | `/api/agents/cinematography` | Shot list and composition |
| `POST` | `/api/agents/visual` | Visual style and asset plan |
| `POST` | `/api/agents/voice` | Narration and delivery plan |
| `POST` | `/api/agents/music-director` | Scene music cues |
| `POST` | `/api/agents/sound-design` | SFX and mix suggestions |
| `POST` | `/api/agents/director` | Legacy research → script → edit |
| `POST` | `/api/agents/research` | Research report |
| `POST` | `/api/agents/screenwrite` | Short-form script |
| `POST` | `/api/agents/edit-video` | Edit and render a video |
| `POST` | `/api/agents/compose-music` | Generate background music |
| `POST` | `/api/agents/produce-short` | Render from script |
| `POST` | `/api/agents/ideas` | Brainstorm video ideas |

### Video & data tools

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/shorts/generate-text-video` | Silent 9:16 text video |
| `POST` | `/api/shorts/generate-sound-video` | ElevenLabs narrated video |
| `POST` | `/api/shorts/generate-audio-video` | Video from uploaded audio |
| `POST` | `/api/lofi/generate-video` | Lofi loop from image + audio |
| `GET` | `/api/pokemon/{identifier}` | Pokemon data |
| `GET` | `/api/weather?location=` | Current weather |
| `GET` | `/api/time?timezone=` | Current time |
| `GET` | `/api/wikipedia/search?query=` | Wikipedia extracts |
| `GET` | `/api/pexels/search?query=` | Pexels photos/videos |

### Examples

**Full production**

`POST /api/agents/production`

```json
{
  "task": "Create a Tokyo travel b-roll short with cinematic energy",
  "short_format": "silent",
  "render_video": true
}
```

**Director pipeline (legacy)**

`POST /api/agents/director`

```json
{
  "task": "Create a weather briefing short about Johannesburg this week",
  "context": "Upbeat tone for commuters",
  "produce_short": true,
  "short_format": "auto"
}
```

**Text video**

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

Output is `1080x1920` at 30 FPS.

## Project structure

```text
FrameFusion/
|-- api/
|   |-- app/
|   |   |-- agents/          # Production studio agents + Framey
|   |   |-- models/
|   |   |-- routers/
|   |   `-- services/
|   |-- generated/           # Rendered MP4s (gitignored)
|   |-- requirements.txt
|   `-- .env
|-- web/
|   |-- src/                 # Framey UI, chat storage, media library
|   `-- package.json
|-- scripts/                 # run-api.mjs, setup-api.mjs
|-- package.json             # npm run dev, setup, …
`-- README.md
```

## Contributing

### GitHub repository topics

`ai` `video-editing` `short-form-video` `generative-ai` `fastapi` `python`
`typescript` `vite` `gemini` `elevenlabs` `pexels` `b-roll` `monorepo`

### PR and issue labels

| Label | Use for |
| --- | --- |
| `api` | Backend, routers, services, Python deps |
| `web` | Frontend, chat UI, media library |
| `agents` | Director, producer, editor, music, research |
| `video` | Rendering, MoviePy, FFmpeg, Pexels footage |
| `audio` | Music, narration, sound design, ElevenLabs |
| `docs` | README, comments, API docs |
| `deps` | Dependabot, npm, pip, root scripts |
| `bug` | Something broken |
| `enhancement` | New feature or improvement |

### Commit scopes (optional)

```text
api: add music director endpoint
web: audio player in chat attachments
agents: wire editor to cinematography plan
docs: update setup instructions
deps: bump vite in web
```

Common scopes: `api`, `web`, `agents`, `video`, `audio`, `docs`, `deps`, `scripts`.

## Notes

- Generated MP4s live in `api/generated/` until manually removed.
- **Text on screen** — copy is measured against the 9:16 safe area. If it does not
  fit on one screen, FrameFusion splits it across up to **3 screens** with balanced
  timing (narrated shorts split audio time by word count per screen).
- Chat history is browser-local only — not synced across devices.
- Output filenames must end in `.mp4` with no path separators.
- Colors use `#RRGGBB` format.
- External APIs (Gemini, Pexels, ElevenLabs) have their own rate limits and billing.

## License

[MIT License](LICENSE)
