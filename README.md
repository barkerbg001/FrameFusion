# FrameFusion

FrameFusion is a monorepo for AI-assisted short-form video creation. The **FastAPI**
backend in `api/` powers specialist agents and video tools. The **Vite + TypeScript**
frontend in `web/` provides **Framey** — the chat UI for research, scripting, b-roll
montages, narration, and rendered MP4s.

## Features

- **Framey chat** — conversational agent with tool calling (research, video, Pexels)
- **9:16 vertical videos** — text shorts, narrated shorts, b-roll montages
- **Pexels b-roll pipeline** — download clips, stitch montages, add narration
- **Specialist agents** — researcher, screenwriter, video editor, idea generator
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

### API

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
GEMINI_MODEL=gemini-2.5-flash
```

| Key | Required for |
| --- | --- |
| `GEMINI_API_KEY` | Framey chat and all Gemini agents |
| `PEXELS_API_KEY` | Pexels search, b-roll download, backgrounds |
| `ELEVENLABS_API_KEY` | Narrated shorts and voiceover on b-roll |

The `.env` file is gitignored. Do not commit secrets.

### Web

```powershell
cd web
npm install
```

## Run

**Terminal 1 — API** (from `api/`):

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API: http://127.0.0.1:8000
- Swagger: http://127.0.0.1:8000/docs

**Terminal 2 — Web** (from `web/`):

```powershell
npm run dev
```

- App: http://127.0.0.1:5173 (proxies `/api` to the backend)

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

```
Framey (director) — chat + full pipeline orchestration
  ├── Researcher
  ├── Screenwriter
  └── Video Editor

Framey tools (in chat):
  Research: weather, Pokemon, Wikipedia, time, Pexels search
  Video: text short, sound short
  Footage: download Pexels clips, stitch montage
  Audio: add narration or audio file to existing video
```

### Pipeline (API)

```
Research → Screenwrite → Video Editor → MP4
```

### B-roll montage (chat tools)

```
download_pexels_footage → stitch_pexels_footage → add_narration_to_video (optional)
```

## API endpoints

### Chat & media

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/chat/health` | Health check |
| `POST` | `/api/chat` | Talk to Framey |
| `GET` | `/api/chat/videos` | List generated MP4s |
| `GET` | `/api/chat/videos/{filename}` | Download/stream a video |

### Agents

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/agents/director` | Full research → script → edit pipeline |
| `POST` | `/api/agents/research` | Unified research report |
| `POST` | `/api/agents/screenwrite` | Short-form script |
| `POST` | `/api/agents/edit-video` | Edit and render a video |
| `POST` | `/api/agents/produce-short` | Render from script (no editor) |
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
