<h1>
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="web/public/brand/wordmark-light.svg" />
    <img src="web/public/brand/wordmark-dark.svg" alt="FrameFusion" width="280" height="64" />
  </picture>
</h1>

AI-assisted short-form video creation that runs on your own computer. One **orchestrator** works
with you: it talks ideas through, writes the brief, hands each production stage to a specialist
(research, script, scene images, narration, render), checks every result and delivers a 9:16 MP4.

The orchestrator has two interchangeable **personalities**, picked in Settings and overridable
per project:

- **Director** – decisive, structured, concise.
- **Creative Partner** – imaginative and conversational.

Both are the same orchestrator with identical specialists, tools, models and permissions; only
the voice changes. See [docs/architecture.md](docs/architecture.md).

The web app (`web/`, vanilla TypeScript + Vite) talks to a Django + Django REST Framework API
(`api/`) backed by SQLite. Every AI and media call runs on the server with keys you save in the
app; keys are encrypted at rest and never sent back to the browser. Long-running work (chat
replies, full productions, renders) runs as background jobs that the UI polls.

> **FrameFusion has no login.** Anyone who can reach the API can use your saved keys and spend
> your credits. It only listens on `127.0.0.1` and only accepts localhost origins by default.
> Do not expose it to a network or the internet. See [SECURITY.md](SECURITY.md).

## Quick start

**Prerequisites:** Python 3.12+, Node.js 20+ (22 recommended), npm, and git. MoviePy downloads
its own FFmpeg build on first render; a system FFmpeg is optional. The commands work in
PowerShell, cmd, bash and zsh.

**Platforms:** developed and tested on Windows; CI runs on Linux (Ubuntu). macOS is expected to
work but is not regularly tested.

**What you need:** an API key for one AI provider (OpenRouter, Google Gemini or Anthropic Claude)
to use the orchestrator. Narration works without a key (Edge TTS, an online Microsoft service).
ElevenLabs and Pexels are optional. The test suite and CI need no keys at all.

```powershell
git clone https://github.com/barkerbg001/FrameFusion.git
cd FrameFusion
npm install
npm run setup     # web deps, api/.venv, pip install, api/.env with generated secrets, migrate
npm run dev       # API on http://127.0.0.1:8000 + web on http://localhost:5173
```

Open http://localhost:5173. The first visit starts the setup guide:

1. **Welcome** – what the orchestrator does, what you need, and which personality it uses.
2. **AI provider** – save a key for at least one of OpenRouter, Google Gemini or Anthropic
   Claude, and test it.
3. **Models** – choose a default provider and model, and optionally a separate model for the
   visual specialist. Both model routes must be ready to continue.
4. **Narration** (optional) – free Edge TTS (default, no key) or ElevenLabs; pick a voice and
   delivery, and preview it.
5. **Stock media** (optional) – Pexels key and search defaults.
6. **Appearance** (optional) – system, dark or light theme.
7. **Review** – check what is set up, then create your first project or go to the workspace.

Progress is saved in SQLite after every step, so closing the tab resumes where you left off.
Optional steps can be skipped; the review lists what each missing integration is needed for.
Nothing is generated and no credits are spent unless you click a button that says so. Reopen the
guide any time from **Settings → Setup guide**.

`npm run setup` creates `api/.env` from `api/.env.example` and fills in `DJANGO_SECRET_KEY` and
`FRAMEFUSION_ENCRYPTION_KEY`. If `api/.env` already exists it only appends missing settings; it
never rewrites existing lines or prints secrets.

### Commands

| Command | What it does |
| --- | --- |
| `npm run dev` | API + web together |
| `npm run dev:api` | API only (`manage.py runserver --noreload`) |
| `npm run dev:api:reload` | API with auto-reload (reloads interrupt running jobs) |
| `npm run dev:web` | Web only (Vite, proxies `/api` to the API) |
| `npm run build` | Typecheck and build the web app into `web/dist` |
| `npm run migrate` | Upgrade an old multi-account database if needed, then apply migrations |
| `npm run manage -- <command>` | Any `manage.py` command |
| `npm run test:api` | API test suite (pytest, providers mocked, no network) |
| `npm run lint:api` / `npm run format:api` | Ruff lint / format |
| `npm run typecheck:api` / `npm run typecheck:web` | mypy / tsc |
| `npm run check:migrations` | Fail if models changed without a migration |
| `npm run ci` | Build, lint, format check, mypy, migration check and tests |

`FRAMEFUSION_HOST` and `FRAMEFUSION_PORT` change where `dev:api` listens (default
`127.0.0.1:8000`), and the Vite dev proxy follows the same variables. If you also move the web
port, add its origin to `FRAMEFUSION_FRONTEND_ORIGINS`. The script refuses a non-loopback host unless `FRAMEFUSION_ALLOW_REMOTE` is
set; read [SECURITY.md](SECURITY.md) first.

<details>
<summary>Manual setup (without the root scripts)</summary>

From `api/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env   # then fill in DJANGO_SECRET_KEY and FRAMEFUSION_ENCRYPTION_KEY
python manage.py upgrade_single_user
python manage.py migrate
python manage.py runserver 127.0.0.1:8000 --noreload
```

From `web/`:

```powershell
npm install
npm run dev
```

</details>

## Integrations

All keys are saved in the app (setup guide or **Settings**), encrypted with
`FRAMEFUSION_ENCRYPTION_KEY`, and only ever shown masked (`••••abcd`). Each card can show/hide
the key while typing, save, replace, test and remove it, and links to the provider's key page.
Keys are redacted from logs, job events and error responses.

| Service | Used for | Connection test | Required |
| --- | --- | --- | --- |
| OpenRouter | Orchestrator and specialists (many model families) | `GET /api/v1/key`, not billed | One AI provider |
| Google Gemini | Orchestrator and specialists | Lists models, not billed | One AI provider |
| Anthropic Claude | Orchestrator and specialists | Lists models, not billed | One AI provider |
| Edge TTS (no key) | Free narration for previews, narrated shorts and full productions | Loading the voice list | Default narration provider; needs internet |
| ElevenLabs | Premium narration (if selected), standalone AI music | Lists voices and reads the subscription, no credits | Optional |
| Pexels | Stock photo/video search, scene images | One curated-photos request, counts toward the hourly quota | Optional |
| Pixabay | Scene images: stock photos, illustrations and vector graphics | One search (free, 100 requests a minute) | Optional |
| Brave Search | Web image *discovery* when licensed sources have nothing (rights unknown, you review) | One image search, uses paid credits | Optional |
| Wikimedia Commons (no key) | Scene images with per-file licences; best for landmarks, people, species, history | – | Used automatically |
| Openverse (no key) | Creative Commons scene images with licence metadata | – | Used automatically; anonymous rate limits apply |

**Models.** Choose a default provider and model, optionally override it for one of two model
routes (*Orchestrator and writing*, or *Visual specialist*), and set temperature or a
response-length limit (shown only when every selected provider supports them). Routes are not
personalities: both personalities use the same routes. FrameFusion never switches providers on
its own: if the selected provider fails, the job fails with a clear message and a link to
Settings.

**Scene images.** FrameFusion would rather leave a scene unresolved than show an unrelated
picture. For each scene the visual specialist:

1. writes a **visual brief**: subject, action, named people/places/things, how specific the
   image must be (exact, representative or generic), visual type, orientation, exclusions and
   up to four search queries that all keep the subject;
2. **searches** the licensed sources suited to the brief (Wikimedia Commons and Openverse first
   for named subjects, Pexels and Pixabay first for generic ones);
3. **inspects** previews with the *Visual specialist* model, without showing it titles or tags,
   because stock titles are often wrong;
4. **ranks** and downloads only candidates that pass, through the SSRF-safe fetcher (public
   addresses and ports 80/443 only, every redirect re-checked, size, type and dimension checks,
   duplicate detection);
5. otherwise **reports a gap**: the scene stays *No suitable image*, with the closest
   alternatives and what a good image would show.

It never takes the first result, never broadens a query until the subject is gone, and never
treats a successful download as proof of relevance. Named subjects (the Eiffel Tower, a
particular person) are only used automatically when the image looks right *and* the source
names it; a look-alike can only be used as a labelled illustration. If your model can't read
images, candidates are judged from metadata only, marked **visually unverified**, and named
subjects always need your review. See [docs/architecture.md](docs/architecture.md#scene-images).

Every image keeps provider, creator, licence, licence URL, attribution, source page and a
checksum. Automatic selection only uses documented licences. Images from Brave, a URL, a
webpage or an upload are marked **rights unknown**; the specialist never places them itself,
and the renderer only uses them after you choose them. Wide images get a separate render
version with the whole picture visible instead of being stretched or cropped through the
subject.

In a project's **Scenes** tab each scene shows its status, brief, the selected image and why,
how it was verified, rights and attribution, and the alternatives. From there you can search
again (any source), paste an image URL or webpage, upload a file, use a title card, or remove
the image; only that scene is re-rendered. FrameFusion has no image generation, so that is not
offered. Licences come from the source; check them before publishing.

#### Finding images with Google Images (you search, FrameFusion does the rest)

FrameFusion never automates Google. Google's terms forbid automated access that ignores its
robots.txt, which disallows `/search` and `/imgres`, and the Custom Search JSON API is closed
to new customers and shuts down on January 1, 2027. So a Google search stays in your own
browser:

1. In the **Scenes** tab, choose **Google Images** on a scene. FrameFusion opens a Google
   Images search for the scene's brief in a new tab.
2. Open a result you like and copy its address. Copying the large image's address also works,
   and so does any publisher page or image link.
3. Paste it into the field and press **Search**. FrameFusion reads the Google result link
   locally (`imgurl`, `imgrefurl`) **without requesting Google**. It then opens the
   publisher's page through the safe fetcher, looks for the original image on that page and
   records the publisher, title and any rights the page states: a schema.org `license`,
   `creditText` or `copyrightNotice`, a `rel="license"` link, or an author or copyright meta
   tag. Other images on that page are offered as well.
4. Each candidate is checked against the brief from its metadata, which is free. **Check with
   vision** starts a background job that makes one paid call to the *Visual specialist* model
   and looks at up to six images.
5. **Approve rights and use for scene N** downloads the image safely and validates it.
   Duplicates are reused. The image is stored with its provenance (found via Google Images,
   publisher, source page, stated licence, checksum).

Images found this way are always **rights unknown**: Google doesn't grant reuse rights, and a
licence stated on the page is recorded as "stated by publisher", not verified. They are never
picked automatically, and they render only after you choose them.

Troubleshooting:

- *"That's Google's preview thumbnail"*: you copied a thumbnail (`encrypted-tbn…gstatic.com` or a
  `data:` image). Open the result and copy the publisher's page or the full-size image instead.
- *"That's a Google results page"*: paste a result's own link, not the search page.
- *"The image wasn't found on the publisher's page"* (tag: *Not seen on the publisher's
  page*): the page loads its images with JavaScript, the image
  has moved, or a CDN serves it under another address. The image itself is still validated,
  but check the page yourself.
- *"Couldn't open the publisher's page"*: paywalls, logins and bot protection are respected,
  never bypassed, and no browser cookies are sent. Download the image yourself and use
  **Upload** instead.
- *"No suitable image found on that link"*: the page has no usable image (too small, logos
  only, or no images). Try another result.

**Pexels** (**Settings → Stock media**): default media type, orientation and minimum size for
stock search and scene images. Results keep the photographer's name and link.

**Pixabay** and **Brave Search** (**Settings → Stock media**): optional keys, tested and stored
like the others. Brave is a paid API and is used at most once per scene, only after the
licensed sources had nothing suitable.

When a feature needs a missing integration, the workspace says which one and links to Settings
instead of failing silently.

### Narration

Narration is set in **Settings → Narration** (also a setup-guide step). It applies to voice
previews, narrated shorts and the voice stage of full productions. Each project can override the
default from the **Narration** tab of its side panel.

| Provider | Cost | Key | Where the text goes |
| --- | --- | --- | --- |
| **Free – Edge TTS** (default) | Free | None | Microsoft's online speech service |
| **ElevenLabs** | Your ElevenLabs credits | ElevenLabs key saved in Settings | ElevenLabs |

**Edge TTS** uses the [`edge-tts`](https://github.com/rany2/edge-tts) Python package, a client for
the online text-to-speech service behind Microsoft Edge's read-aloud feature. It is **not offline
or local synthesis**: the server sends the narration text to Microsoft over the internet and
receives MP3 audio with word timings. It needs no API key. You can search the voice list by
name, language, gender or style, preview any voice, and adjust rate (−50 % to +100 %), pitch
(±50 Hz) and volume (±50 %). The default voice is `en-US-EmmaMultilingualNeural`.

It is installed with the other API dependencies (`npm run setup` does this for you):

```powershell
cd api
.\.venv\Scripts\python.exe -m pip install -r requirements.txt   # includes edge-tts>=7.2,<8
# or just the narration client:
.\.venv\Scripts\python.exe -m pip install "edge-tts>=7.2,<8"
```

On macOS or Linux use `.venv/bin/python -m pip install -r requirements.txt`.

**ElevenLabs** narration uses the voice, speech model and voice settings saved under the ElevenLabs
part of Settings → Narration, and spends your credits. Previews with ElevenLabs also use credits
(limited to 300 characters) and only run when you click **Preview narration**.

**No silent switching.** FrameFusion never falls back from one narration provider to the other.
If narration fails, the job stops with a "Narration could not be recorded" message that names the
provider and links to Settings → Narration. **Retry narration** re-records only the voice track
and reuses the planned script, visuals and music, so the rest of the production is not paid for
again. You can also retry with the other provider explicitly. ElevenLabs is offered only when a
key is saved.

**Limitations of Edge TTS.** The service is unofficial and undocumented. Microsoft can change,
rate-limit or withdraw it at any time, and FrameFusion makes no promise about its availability,
usage limits or the rights to use its audio commercially. Check Microsoft's terms for your use.
Some voices are retired over time; a saved voice that is no longer offered is reported clearly.
FrameFusion keeps at most two syntheses running at once, retries network errors up to three
times, and caches the voice list in memory for 12 hours.

#### Troubleshooting narration

| Symptom | What to do |
| --- | --- |
| "Couldn't reach the Edge TTS service" | Check the internet connection and any proxy or firewall that blocks `speech.platform.bing.com` (WebSocket over HTTPS), then click **Retry narration**. |
| "Edge TTS returned no audio for the voice …" | The voice may be retired or briefly unavailable. Pick another voice in Settings → Narration, or retry later. |
| "… is no longer offered" | Refresh the voice list in Settings → Narration and choose a current voice. Check project overrides too. |
| Voice list empty or stale | Use the refresh button next to the voice filters (bypasses the 12-hour cache). |
| `ModuleNotFoundError: edge_tts` | Install the dependencies again with the pip command above, then restart the API. |
| Clock-skew errors | Make sure the system clock is set automatically; the service rejects requests from a badly skewed clock. |
| ElevenLabs "not configured" | Save an ElevenLabs key in Settings → Narration, or switch the provider back to Edge TTS. |

**Keys from an older `api/.env`.** If `api/.env` still contains `OPENROUTER_API_KEY`,
`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` or
`PEXELS_API_KEY`, import them once and then delete those lines:

```powershell
npm run manage -- import_env_keys            # add --replace to overwrite saved keys
```

## Configuration

Server settings live in `api/.env` (git-ignored). `api/.env.example` documents every variable;
the important ones:

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | **Required.** Signs CSRF tokens. |
| `FRAMEFUSION_ENCRYPTION_KEY` | **Required to save keys.** Fernet key that encrypts saved keys. Comma-separate keys to rotate (newest first). Without it the app shows a banner and refuses to store keys. |
| `DJANGO_DEBUG` | `true` for local development only. |
| `DJANGO_ALLOWED_HOSTS` | Host names the API answers to (localhost only unless remote access is allowed). |
| `FRAMEFUSION_FRONTEND_ORIGINS` | Browser origins allowed to call the API (CORS + CSRF). |
| `FRAMEFUSION_HOST` / `FRAMEFUSION_PORT` | Address `npm run dev:api` binds to. |
| `FRAMEFUSION_ALLOW_REMOTE` | Opt-in for non-localhost hosts or origins. Only for setups protected by your own authentication; see SECURITY.md. |
| `DJANGO_SECURE_COOKIES` | Secure cookies; defaults to the opposite of `DJANGO_DEBUG`. |
| `FRAMEFUSION_DB_PATH` | SQLite file (default `api/var/framefusion.sqlite3`). |
| `FRAMEFUSION_UPLOAD_DIR` / `FRAMEFUSION_OUTPUT_DIR` | Uploaded inputs / rendered media. |
| `FRAMEFUSION_MAX_UPLOAD_MB` | Upload size limit. |
| `FRAMEFUSION_JOB_WORKERS` | Background job threads. |
| `FRAMEFUSION_LLM_TIMEOUT_SECONDS` / `FRAMEFUSION_LLM_MAX_RETRIES` | Per-call timeout and bounded retries for transient provider errors. |
| `FRAMEFUSION_*_FALLBACK_MODELS` | Model ids offered when live model discovery fails. |

API keys are not configured through environment variables.

## Data, backups and upgrades

SQLite runs in WAL mode with short transactions. It stores projects, messages, generation jobs
and their events, media records, app settings (theme, setup progress, AI and media preferences)
and encrypted keys. The database, uploads, rendered media, `.env` and other runtime artifacts are
git-ignored by the root `.gitignore`.

**Backups.** Stop the API, then copy `api/var/framefusion.sqlite3` (plus any `-wal`/`-shm` files
beside it), or take a live backup with
`sqlite3 api/var/framefusion.sqlite3 ".backup 'framefusion-backup.sqlite3'"`. Back up
`api/generated/` for rendered media and store `FRAMEFUSION_ENCRYPTION_KEY` separately (for
example in a password manager). Without that key, saved keys cannot be decrypted and must be
re-entered.

### Upgrading from the multi-account version

Earlier builds had sign-up and per-user data. To upgrade, stop the API and run:

```powershell
npm run migrate        # npm run setup does the same
```

`upgrade_single_user` detects the old schema and then:

1. moves the old database aside as `framefusion.accounts-backup-<timestamp>.sqlite3` (kept until
   you delete it);
2. creates a fresh single-user database;
3. imports every account's projects, messages, jobs, job events and media. Project IDs are
   kept. If two accounts used the same legacy chat ID, the second is prefixed with the username.
4. applies settings that all accounts agree on (identical keys, AI defaults, overrides,
   theme).

Settings that differ between accounts, such as two different OpenRouter keys or different
default models, are **not applied or merged**. Each one becomes a pending choice. Resolve them
in **Settings → Data → Imported settings**, where keys are shown masked, or from the command line:

```powershell
npm run manage -- resolve_import_conflicts --list
npm run manage -- resolve_import_conflicts --choose credential:openrouter=u2 --choose theme=keep_current
npm run manage -- resolve_import_conflicts --prefer alice   # take one account's value everywhere
```

Account tables exist only in the backup file. The new database has no account models. To
import a backup again later, use `npm run manage -- import_account_data --from <file>`. It is
idempotent and skips records that already exist.

### Browser-only chats

The first version kept chats in browser `localStorage` and wrote MP4s to `api/generated/`.
Imports are additive and repeatable; already-imported records are skipped.

- In the browser that has the old chats: **Settings → Data → Preview import / Import**.
- From another machine: run `copy(localStorage.getItem("framefusion:chats"))` in the old
  browser's console, save it as `chats.json`, then:

```powershell
npm run manage -- import_legacy_chats --file chats.json --dry-run
npm run manage -- import_legacy_chats --file chats.json
npm run manage -- import_legacy_media --dry-run
npm run manage -- import_legacy_media
```

## Architecture

```text
api/
  config/      Django settings, URLs, WSGI/ASGI
  common/      Request protections (localhost guard, CSRF), HTTP helpers, error normalisation
  providers/   App settings, encrypted keys, AI/media preferences, onboarding state,
               connection tests, model discovery, account-era import;
               clients/ has the OpenRouter, Gemini and Anthropic clients behind one interface
  studio/      Projects, messages, background jobs + events, production tasks, media,
               image search/download endpoints, agent endpoints, legacy import commands
  tools/       Pexels/Wikipedia/weather/time/Pokemon lookups and render tools (as jobs)
  engine/      orchestrator/ (personalities, chat, specialists, persisted production run,
               registry), services/images/ (visual briefs, safe fetch, Pexels/Pixabay/
               Wikimedia/Openverse/Brave/URL/webpage sources, vision relevance checks, image
               toolkit, render variants), timeline renderer, QC, narration (Edge TTS or ElevenLabs);
               reads keys and defaults through engine/integrations.py
  tests/       pytest suite with mocked providers
web/
  src/api.ts         Typed API client (cookies + CSRF; no keys in the browser)
  src/views/         Onboarding, Studio, project workspace, Media, Agents, Settings;
                     integrations.ts holds the key cards and settings panels both reuse
  src/styles/        tokens.css (themes; red brand, blue secondary, red/blue personality
                     tones, status colours) and app.css
  src/assets/        agents/ (Creative Partner and Director avatars), illustrations/
                     (onboarding and empty states); icons come from lucide
  public/            favicon.svg (logo mark), app icons, web manifest, brand/ wordmarks
scripts/       setup-api.mjs, run-api.mjs, run-api-tool.mjs
```

**Request protection.** There are no accounts. Instead, `ALLOWED_HOSTS` is limited to localhost,
which also blocks DNS rebinding. A middleware rejects API requests that browsers mark as
cross-site or that come from unlisted origins. DRF enforces the CSRF token on every unsafe
request. Starting with a non-local host or origin fails unless `FRAMEFUSION_ALLOW_REMOTE` is
set.

**Provider layer.** `providers/clients` normalises messages, system instructions, tool calls,
structured output, usage and errors (`invalid_credentials`, `rate_limited`, `not_configured`,
`provider_error`, ...) across the three AI providers. Calls have timeouts, and only transient
failures are retried, a bounded number of times. Agents resolve their provider and model as
`agent → route → provider/model/key`.

**Jobs.** `POST` endpoints that call a model or render media return `202` with a job. Jobs run
on an in-process thread pool, record progress as events, and can be cancelled or retried.
`GET /api/jobs/<id>?after=<seq>` returns the job plus new events. Jobs that were running when
the server stopped are marked interrupted, and can be retried.

**Hierarchy.**

```text
You → Orchestrator (Director or Creative Partner)
        → specialists: research, script, visual, ideas, music
        → services: narration, music bed, timeline renderer, quality check
        → artifacts (brief, script, scene images, narration, video) → final MP4
```

Specialists report only to the orchestrator and never delegate to each other. A full
production runs these stages as persisted tasks: brief → research → script → visuals →
narration → music → render → QC. Each task is *proposed*, *active*, *completed*, *verified*,
*failed*, *cancelled*, *skipped* or *invalidated*. Unchanged verified stages are reused,
changing a stage invalidates everything downstream, and a failed or cancelled run resumes from
where it stopped. Details in [docs/architecture.md](docs/architecture.md).

## API overview

All endpoints are under `/api`. `GET /api/app` sets the CSRF cookie; unsafe methods need the
`X-CSRFToken` header.

| Area | Endpoints |
| --- | --- |
| App | `GET app` (theme, personality, setup progress, readiness, integrations, pending import choices), `PUT settings/appearance`, `PUT settings/personality`, `GET/PUT settings/onboarding` |
| Keys and AI | `GET settings/providers`, `PUT/DELETE settings/providers/<service>/key`, `POST settings/providers/<service>/test`, `GET settings/providers/<p>/models`, `GET/PUT settings/ai` |
| Media settings | `GET/PUT settings/media`, `GET settings/media/elevenlabs/voices`, `GET settings/media/elevenlabs/models` |
| Narration | `GET/PUT settings/narration`, `GET settings/narration/edge/voices?refresh=1`, `POST narration/preview` (job; ElevenLabs uses credits), `GET narration/previews/<job>` |
| Import choices | `GET settings/import-conflicts`, `POST settings/import-conflicts/<id>` |
| Projects | `GET/POST projects`, `GET/PATCH/DELETE projects/<id>` (PATCH accepts `title` and `personality`), `POST projects/<id>/messages` (job), `POST projects/<id>/production` (job), `POST projects/<id>/production/rerun` (job, optional `from_stage`), `POST projects/import-legacy` |
| Scene images | `POST projects/<id>/images/search` (`source`: `auto`, `pexels`, `pixabay`, `wikimedia`, `openverse`, `brave`, `url`, `webpage`, `link` for a pasted Google Images result, page or image link; optional `scene_index` adds a metadata assessment), `POST projects/<id>/images/check` (job: vision check of up to six `candidate_ids` for a `scene_index`; one paid model call), `POST projects/<id>/images/download` (by `candidate_id`, optional `scene_index`, `illustrative`), `POST projects/<id>/images/upload` (multipart `file`, `scene_index`), `PUT projects/<id>/scenes/<n>/image` (`asset_id`, `null`, or `title_card: true`) |
| Jobs | `GET jobs`, `GET jobs/<id>?after=`, `POST jobs/<id>/cancel`, `POST jobs/<id>/retry`, `POST jobs/<id>/retry-narration` (optional `provider`) |
| Agents | `GET agents/registry`, `GET agents/status`, `POST agents/<slug>` (job) |
| Media | `GET media`, `DELETE media/<id>`, `GET media/<id>/file` (supports `Range`) |
| Tools | `GET pexels/search`, `GET pexels/photos/search`, `GET pexels/videos/search`, `GET wikipedia/search`, `GET weather`, `GET time`, `GET pokemon/<id>` |
| Render tools (jobs) | `POST shorts/generate-text-video`, `POST shorts/generate-sound-video`, `POST shorts/generate-audio-video`, `POST lofi/generate-video`, `POST video-producer/text-short`, `POST video-producer/sound-short` |
| Legacy | `GET chat/health`, `GET chat/videos`, `GET chat/videos/<file>`, `GET chat/audio/<file>` |

`<service>` is one of `openrouter`, `gemini`, `anthropic`, `elevenlabs`, `pexels`, `pixabay`,
`brave`.

## Known limitations

- Single user, no login: suitable for your own machine only (see SECURITY.md).
- The job runner is in-process: run a single API process. Auto-reload or a restart interrupts
  running jobs (they are marked interrupted and can be retried).
- Progress is reported per step through job events; tokens are not streamed to the browser.
- Which generation parameters a Gemini model accepts is only confirmed when it is called.
- ElevenLabs keys restricted to text-to-speech cannot list models; common models are offered
  instead.
- Free narration needs an internet connection and depends on Microsoft's unofficial Edge
  read-aloud service, which can change or stop working without notice (see Narration).
- The old YouTube and lofi file-path endpoints were removed; `lofi/generate-video` takes uploads.
- Image sources have rate limits; when they are hit, scenes are reported as gaps rather than
  filled with something else. Licence metadata comes from the source and is not verified.
- Relevance checks are only as good as the *Visual specialist* model. Without a vision-capable
  model, images are judged from their metadata, marked visually unverified, and named subjects
  always need your review. Even with vision, a model can't guarantee that a photo shows one
  specific person or place; the relevance score is a heuristic, not a probability.
- Niche subjects often have no licensed image at all. Expect *No suitable image* scenes and use
  upload, a URL or a title card for them.
- There is no image-generation integration.
- Google Images is never automated or scraped: you search in your own browser and paste a
  result. Pasted links don't always lead to a usable original (JavaScript-only pages, paywalls,
  hotlink protection), and their rights always need your review.
- The production music bed is procedural. ElevenLabs music is only used when you ask the music
  specialist for a standalone track.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). Security
notes and how to report a vulnerability privately are in [SECURITY.md](SECURITY.md).

## License

FrameFusion's source code is released under the [MIT License](LICENSE). Third-party packages,
bundled assets and external services have their own terms; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Media you generate with FrameFusion can contain
material from AI providers, Microsoft's speech service, ElevenLabs, Pexels, Openverse or other
sources. Check those terms and each asset's licence before you publish or sell it.
