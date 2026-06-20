# FrameFusion

FrameFusion is a monorepo for generating vertical text videos and providing
data tools that can be called by AI agents. It includes a FastAPI backend in
`api/` and a Vite + TypeScript frontend in `web/`.

The API currently supports:

- 9:16 text videos with centered text and solid-color backgrounds
- Text-to-speech videos generated with ElevenLabs
- Videos made from uploaded audio
- Lofi videos made from uploaded images and audio
- Pokemon data lookup
- Current time lookup by timezone
- Current weather lookup by location
- Gemini weather research agent with multi-day forecasts
- YouTube video downloads

## Project Structure

```text
FrameFusion/
|-- api/
|   |-- app/
|   |   |-- main.py
|   |   |-- agents/
|   |   |-- models/
|   |   |-- routers/
|   |   `-- services/
|   |-- requirements.txt
|   `-- .env
|-- web/
|   |-- src/
|   |-- package.json
|   `-- ...
|-- .github/
|   `-- dependabot.yml
`-- README.md
```

## Requirements

### API

- Python 3.10 or newer
- FFmpeg available to MoviePy
- An ElevenLabs API key for text-to-speech videos

### Web

- Node.js 20 or newer
- npm

## Setup

### API

From the `api` directory, create and activate a virtual environment:

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```powershell
pip install -r requirements.txt
```

Create a `.env` file in `api/`:

```dotenv
ELEVENLABS_API_KEY=your_api_key

# Optional: override the default ElevenLabs voice.
ELEVENLABS_VOICE_ID=your_voice_id
```

The `.env` file is ignored by Git. Do not commit API keys.

### Web

From the `web` directory:

```powershell
cd web
npm install
```

## Run the API

From the `api` directory:

```powershell
uvicorn app.main:app --reload
```

The API is available at:

- API: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI schema: `http://127.0.0.1:8000/openapi.json`

## Run the Web App

From the `web` directory:

```powershell
npm run dev
```

The dev server is available at `http://127.0.0.1:5173`.

Other useful commands:

```powershell
npm run build    # production build to dist/
npm run preview  # preview the production build
```

## Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/shorts/generate-text-video` | Generate a silent 9:16 text video |
| `POST` | `/api/shorts/generate-sound-video` | Generate narration with ElevenLabs and create a 9:16 video |
| `POST` | `/api/shorts/generate-audio-video` | Create a 9:16 video from uploaded audio |
| `POST` | `/api/lofi/generate-video` | Create a lofi video from uploaded images and audio |
| `GET` | `/api/pokemon/{identifier}` | Get Pokemon data by name or Pokedex number |
| `GET` | `/api/time` | Get the current time in an IANA timezone |
| `GET` | `/api/weather` | Get current weather for a location |
| `GET` | `/api/wikipedia/search` | Search Wikipedia and return cited article extracts |
| `POST` | `/api/agents/anime-research` | Research an anime with citations and spoiler controls |
| `POST` | `/api/agents/history-research` | Research a historical topic with citations |
| `POST` | `/api/agents/pokemon-research` | Research a Pokemon with Gemini and PokeAPI |
| `POST` | `/api/agents/weather-research` | Research current and forecast weather with Gemini |
| `GET` | `/api/youtube/download-video` | Download a YouTube video |

## Generate a Text Video

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

`background_color` can be omitted to select a random color. The generated MP4
is `1080x1920` at 30 FPS.

## Generate an ElevenLabs Sound Video

`POST /api/shorts/generate-sound-video`

```json
{
  "text": "Pikachu stores electricity inside its cheek pouches.",
  "voice_id": null,
  "model_id": "eleven_multilingual_v2",
  "language_code": "en",
  "background_color": "#F4A261",
  "text_color": "#FFFFFF",
  "font_size": 96,
  "output_name": "pikachu-fact.mp4"
}
```

FrameFusion sends the text to ElevenLabs, creates an MP3 narration, matches the
video duration to the narration, and returns the final MP4. Audio is limited to
60 seconds.

When `voice_id` is omitted, FrameFusion uses `ELEVENLABS_VOICE_ID` from `.env`
or its built-in default voice.

## Generate a Video From Uploaded Audio

`POST /api/shorts/generate-audio-video`

This endpoint accepts `multipart/form-data`.

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/shorts/generate-audio-video" `
  -F "audio=@C:\path\to\sound.mp3" `
  -F "text=Text displayed in the center" `
  -F "background_color=#264653" `
  -F "text_color=#FFFFFF" `
  -F "font_size=96" `
  -F "output_name=audio-short.mp4" `
  --output audio-short.mp4
```

Supported audio formats are AAC, FLAC, M4A, MP3, OGG, and WAV.

## Pokemon Tool

Look up a Pokemon by name:

```http
GET /api/pokemon/pikachu
```

Or by National Pokedex number:

```http
GET /api/pokemon/25
```

The response includes types, abilities, stats, measurements, description,
generation, habitat, and artwork URLs. Data is provided by
[PokeAPI](https://pokeapi.co/).

Agent-callable service function:

```python
from app.services.pokemon_client import get_pokemon_data

pokemon = get_pokemon_data("pikachu")
```

## Pokemon Research Agent

`POST /api/agents/pokemon-research`

```json
{
  "identifier": "pikachu",
  "question": "Create a factual briefing for a short video."
}
```

The Gemini agent calls the PokeAPI tool and returns:

- A factual summary
- Verified facts
- A base-stat profile
- Notable traits
- Short-form content hooks
- A 45–90 word video script
- Research limitations
- The exact PokeAPI source data used during research

The agent avoids unsupported claims about moves, evolutions, matchups, games,
and anime events when those details are not present in the source data.

## History Research Agent

`POST /api/agents/history-research`

```json
{
  "topic": "Apollo 11",
  "question": "Why was the mission historically significant?",
  "max_sources": 3
}
```

The history agent searches English Wikipedia through the official MediaWiki
API, asks Gemini to analyze the retrieved extracts, and returns:

- A cited historical summary
- A chronological timeline
- Key people, causes, and consequences
- Verified facts and uncertainties
- Short-form content hooks
- A cited 60–120 word video script
- Source titles and URLs
- The exact source extracts used during research

Wikipedia is a tertiary source. Important historical claims should be checked
against primary documents or scholarly publications before publishing.

## Wikipedia Tool

```http
GET /api/wikipedia/search?query=Apollo%2011&max_sources=3
```

Agent-callable service function:

```python
from app.services.wikipedia_client import search_wikipedia

sources = search_wikipedia("Apollo 11", max_sources=3)
```

The history and anime agents both use this general tool, with filtering and
prompts appropriate to their research domains.

## Anime Research Agent

`POST /api/agents/anime-research`

```json
{
  "title": "Fullmetal Alchemist: Brotherhood",
  "question": "Why is this series notable?",
  "max_sources": 3,
  "allow_spoilers": false
}
```

The anime researcher returns:

- A cited, spoiler-aware summary and premise
- Sourced format, release, creator, and studio facts
- Themes clearly separated from factual claims
- Verified facts and short-form hooks
- A cited 60–120 word video script
- Source titles, URLs, and exact extracts

Wikipedia remains a tertiary source. Official sites and specialist anime
databases may provide more complete production and episode information.

## Time Tool

```http
GET /api/time?timezone=Africa/Johannesburg
```

Use an IANA timezone such as `UTC`, `Africa/Johannesburg`, or
`America/New_York`.

Agent-callable service function:

```python
from app.services.time_tool import get_current_time

current_time = get_current_time("Africa/Johannesburg")
```

## Weather Tool

```http
GET /api/weather?location=Johannesburg
```

The response includes temperature, apparent temperature, conditions, humidity,
precipitation, cloud cover, and wind information. Weather and geocoding data
are provided by [Open-Meteo](https://open-meteo.com/).

Agent-callable service function:

```python
from app.services.weather_client import get_current_weather

weather = get_current_weather("Johannesburg")
```

## Weather Research Agent

`POST /api/agents/weather-research`

```json
{
  "location": "Johannesburg",
  "question": "Is tomorrow suitable for an outdoor walk?",
  "forecast_days": 3
}
```

The Gemini agent calls the Open-Meteo weather tool, evaluates the current
conditions and forecast, and returns a structured report with:

- A concise summary
- Current conditions
- One outlook item per forecast day
- Weather risks
- Practical recommendations
- Data limitations
- The exact Open-Meteo source data used during research

This endpoint requires `GEMINI_API_KEY` in `.env`. You can optionally set
`GEMINI_MODEL`; the default is `gemini-2.5-flash`.

## Notes

- Generated files are temporary and are deleted after the response completes.
- Text is automatically wrapped and scaled to fit the vertical frame.
- Colors must use the `#RRGGBB` format.
- Output filenames must end in `.mp4` and cannot contain a path.
- External services may enforce their own rate limits and usage charges.

## License

FrameFusion is available under the [MIT License](LICENSE).
