# Working on FrameFusion

Monorepo: Django + DRF API in `api/`, vanilla TypeScript + Vite web app in `web/`, Node helper
scripts in `scripts/`. See `README.md` for setup and the API overview, `CONTRIBUTING.md` for
the full checklist and `SECURITY.md` for the deployment model.

FrameFusion is **single-user with no login**:

- one `AppSettings` row (theme, onboarding progress, AI and media preferences);
- one encrypted `ProviderCredential` per service: `openrouter`, `gemini`, `anthropic`,
  `elevenlabs`, `pexels`;
- protection comes from localhost-only hosts and origins, a cross-site guard and CSRF
  (`common/security.py`).

## Commands

- Setup: `npm install && npm run setup` (creates `api/.venv`, `api/.env` with generated secrets,
  upgrades an old multi-account database, migrates)
- Run: `npm run dev` (API `127.0.0.1:8000`, web `localhost:5173`, Vite proxies `/api`)
- Before finishing a change: `npm run ci` and `npm run typecheck:web`
  (build, ruff check + format check, mypy, `makemigrations --check`, pytest)
- Django commands: `npm run manage -- <command>`; new migrations: `npm run manage -- makemigrations`
- Database upgrade from the multi-account version: `npm run migrate` (runs `upgrade_single_user`);
  differing settings are resolved with `resolve_import_conflicts` or in Settings → Data

## Rules

**Data and keys**

- Never read, print or commit `api/.env`, the SQLite database or its backups (`api/var/`),
  uploads or `api/generated/`.
- All AI, ElevenLabs and Pexels calls go through the backend with the encrypted key
  (`providers/`, read by engine code via `engine/integrations.py`).
  - Never send keys to the browser, store them in browser storage, log them, or put them in
    URLs or errors.
  - Never read keys from environment variables at runtime or add a shared credential.
  - Use `providers.clients.redact` for anything that might echo a key.
- Never fall back to a different provider or model silently; fail with a normalised `LLMError`.
  A missing optional integration raises `IntegrationNotConfigured` (code `not_configured`, with
  `service`) or becomes a recorded limitation.

**Security and paid work**

- Don't add accounts, public endpoints or weaken `LocalRequestGuardMiddleware`, CSRF or the
  `FRAMEFUSION_ALLOW_REMOTE` start-up check.
- Never start paid generation automatically. Previews, chats, productions and renders run only
  after an explicit user action. Onboarding never generates anything.
- Look up projects and jobs with `get_project` / `get_job` in `studio/views.py` so missing IDs
  return 404.
- Work that calls a model or renders media must run as a `GenerationJob` (`studio/jobs.py`) and
  return `202`; keep transactions short and call `jobs.submit` outside `transaction.atomic`.
- Views stay thin: orchestration lives in `engine/`, provider code in `providers/clients/`.
- Tests mock providers (`tests/conftest.py` `fake_providers`, `httpx.MockTransport` for media
  clients) and must not hit the network.

**Frontend**

- Build DOM with `h()` (text via `textContent`) and render Markdown only through `markdown.ts`
  (DOMPurify).
- Use tokens from `styles/tokens.css`:
  - red `--brand` / `--brand-solid` for primary actions, the logo and the active-nav marker;
  - blue `--accent` for secondary interactions, selection, checked controls and `--focus`;
  - `--framey` (red, Creative Partner) and `--reel` (blue, Director) for the orchestrator's
 personality, applied through the `tone-framey` / `tone-reel` classes (`--tone*` variables);
  - status colours only for status. Destructive actions use `button-danger` (outlined, labelled,
    with an icon), never a solid red fill that looks like the primary button.
- Icons come only from `lucide` through `icon()` in `dom.ts` (stroke 1.75); icon-only buttons
  need an `aria-label`. No emoji or inline SVG icons; the logo is `brandMark()` in `shell.ts`.
- Keep light, dark and system themes and `prefers-reduced-motion` working. Avatars live in
  `src/assets/agents/`, illustrations in `src/assets/illustrations/` (local WebP); don't add
  assets that nothing uses.

**Agents** (see `docs/architecture.md`)

- One orchestrator (`engine/orchestrator/`) with two personalities, `director` and
 `creative_partner`. Personalities change only the voice (`personality_block`); prompts, tools,
 models and permissions must stay identical. The personality is snapshotted per job
 (`job.input["personality"]`), so a switch applies at the next turn.
- Model routes (`planner`, `production`) are not personalities; don't mix the two.
- Hierarchy is user → orchestrator → specialists/services → artifacts. Specialists never call
 each other (`delegated()` enforces depth); add capabilities as orchestrator or specialist tools.
- Production stages are persisted `ProductionTask`s. Reuse verified tasks by input hash,
 invalidate downstream on change, and report `step` events with `stage` and `status`.
- Image downloads go through `engine/services/images/safe_fetch.py` only. Automatic selection
 uses documented licences only; keep provider, creator, licence, attribution and checksum on
 the `MediaAsset`. The browser downloads by `candidate_id`, never by posting metadata.

**Narration**

- Narration goes through `engine/services/narration.py`: free Edge TTS (`edge-tts`, an
  **online** Microsoft service, never call it offline or local) or ElevenLabs (credits).
- Never fall back from one narration provider to the other. A failure raises a narration error
  (`kind: narration_failed`); the user retries with `POST jobs/<id>/retry-narration`.
- Mock `edge_tts` and ElevenLabs in tests.
- Settings UI pieces live in `views/integrations.ts` and are shared by Settings and the
  onboarding wizard (`views/onboarding.ts`). Reuse them.
