# Contributing to FrameFusion

Thanks for helping. This guide covers local setup, the checks a change must pass, and the
rules that keep keys and data safe.

## Setup

```powershell
npm install
npm run setup     # web deps, api/.venv, api/.env with generated secrets, database migrations
npm run dev       # API on http://127.0.0.1:8000, web on http://localhost:5173
```

The commands work in PowerShell, cmd, bash and zsh. Windows is used day to day and Linux runs in
CI; macOS should work but is not regularly tested. Please report platform problems.

The first visit opens the setup guide. You need a key for one AI provider to run the orchestrator.
Tests never need real keys.

### Working without paid keys

- `npm run ci`, `npm run typecheck:web` and the whole test suite run with no keys and no network:
  every provider, Edge TTS and ElevenLabs is mocked.
- The setup guide only lets you past the **AI provider** step once a key is saved for OpenRouter,
  Gemini or Anthropic. Saving a key does not call the provider; a connection test does, and is
  not billed. Some providers offer free-tier keys or free models; check their current terms.
- Narration works without a key through Edge TTS, which is free but **online**: it sends the text
  to Microsoft's speech service. ElevenLabs and Pexels are optional; features that need them say
  so and link to Settings.
- Nothing is generated automatically, so browsing the UI never spends credits.

### Sample data and secrets

- The repository holds no sample database, media or keys. Your database (`api/var/`), uploads,
  rendered media (`api/generated/`) and `api/.env` are git-ignored; keep them that way.
- Test data lives in `api/tests/` (fixtures and dummy keys). Dummy keys must be obviously fake.
  Mark them `# gitleaks:allow (dummy)` if they look like a real key format.
- Don't add downloaded or AI-generated media without recording its source and licence in
  `THIRD_PARTY_NOTICES.md`.

Layout:

- `api/`: Django + DRF.
  - `providers/`: settings, keys, onboarding and provider clients.
  - `studio/`: projects, jobs and media.
  - `tools/`: lookups and render tools.
  - `engine/`: agents and media services.
- `web/`: vanilla TypeScript + Vite.
- `scripts/`: Node helpers used by the root `package.json`.

## Before opening a pull request

```powershell
npm run ci             # web build, ruff check, ruff format --check, mypy, makemigrations --check, pytest
npm run typecheck:web
```

- Format Python with `npm run format:api` (Ruff, line length 100).
- Model changes need a migration: `npm run manage -- makemigrations`.
- Add or update tests in `api/tests/`. Providers are mocked (`tests/conftest.py` `fake_providers`,
  `httpx.MockTransport` for media clients); tests must not use the network or real keys.
- For UI changes, check both themes, a narrow (mobile) viewport, keyboard navigation and
  `prefers-reduced-motion`.
- Update `README.md` when commands, settings or endpoints change.

CI (`.github/workflows/ci.yml`) runs on every pull request with read-only permissions and no
repository secrets:

- web typecheck and build;
- the API checks above;
- a Gitleaks scan of the full history;
- `npm audit` and `pip-audit`.

Known, assessed advisories are listed with reasons in `api/pip-audit-ignore.txt`. Dependabot
opens grouped dependency updates.

Optional local secret scanning with [pre-commit](https://pre-commit.com):

```powershell
pip install pre-commit
pre-commit install      # runs Gitleaks on staged changes before each commit
```

Labels: `api`, `web`, `agents`, `video`, `audio`, `docs`, `deps`, `bug`, `enhancement`.
Commit scopes (optional): `api`, `web`, `agents`, `video`, `audio`, `docs`, `deps`, `scripts`.

## Rules for changes

**Keys and privacy**

- Never commit, print or paste the contents of `api/.env`, `api/var/` (database and backups),
  uploads or `api/generated/`.
- Every provider call (AI, ElevenLabs, Pexels) happens on the server with the encrypted key from
  `providers/`. Never send a key to the browser, store it in browser storage, put it in a URL,
  log it or include it in an error. Pass anything that might echo a key through
  `providers.clients.redact`.
- Engine code reads keys and media defaults through `engine/integrations.py`. When an optional
  integration is missing, raise `IntegrationNotConfigured` or degrade with a clear limitation;
  never use a hard-coded or environment key.
- Never fall back to a different AI provider or model silently; fail with a normalised
  `LLMError`.

**Single-user boundaries**

- FrameFusion has no accounts. Don't weaken the localhost guard, CSRF enforcement or the
  `FRAMEFUSION_ALLOW_REMOTE` start-up check (see `SECURITY.md`).
- Endpoints that spend credits run only on an explicit user action; nothing paid may start
  automatically (on page load, during onboarding, or in a connection test that costs money).

**Jobs and views**

- Work that calls a model or renders media runs as a `GenerationJob` (`studio/jobs.py`) and
  returns `202`. Keep transactions short and call `jobs.submit` outside `transaction.atomic`.
- Keep views thin: orchestration lives in `engine/`, provider code in `providers/clients/`.

**Frontend**

- Build DOM with `h()` (text via `textContent`) and render Markdown only through `markdown.ts`.
- Use colours from `styles/tokens.css`:
  - red `--brand` / `--brand-solid` for primary actions and the logo;
  - blue `--accent` for secondary interactions, selection and the `--focus` ring;
  - `--framey` (red, Creative Partner) and `--reel` (blue, Director) for the orchestrator's
    personality, applied through the `tone-framey` / `tone-reel` classes;
  - `--ok`, `--warn` and `--danger` only for status. Destructive buttons use `button-danger`
    (outlined, with an icon and an explicit label).
- Icons come from `lucide` through `icon()` in `dom.ts`; icon-only buttons need an `aria-label`.
- Reuse the settings building blocks in `views/integrations.ts` instead of duplicating them.

**Narration**

- Free narration uses `edge-tts`, a client for Microsoft's **online** speech service. Don't
  describe it as offline or local, and don't promise availability, limits or commercial rights.
- Narration failures must reach the user (`narration_failed`, with a retry); never switch
  providers automatically. Mock `edge_tts` and ElevenLabs in tests.

**Agents**

- There is one orchestrator (`engine/orchestrator/`) with two personalities, `director` and
  `creative_partner`. A personality changes only the voice (`personality_block`); prompts,
  tools, models and permissions stay identical. See [docs/architecture.md](docs/architecture.md).
- Specialists report to the orchestrator and never call each other (`delegated()` enforces this).

## Extending FrameFusion

**A new AI provider**

1. Add it to `Provider` in `providers/models.py` and create a migration.
2. Implement a `ProviderClient` in `providers/clients/` and register it in `CLIENTS` in
   `providers/clients/__init__.py`. Normalise errors to `LLMError` codes and redact keys.
3. Wire the key card, connection test and model discovery in `providers/services.py`, and the
   UI in `web/src/views/integrations.ts`.
4. Add tests with mocked HTTP (see `tests/test_provider_clients.py`).

**A new media integration** (like Pexels or ElevenLabs)

1. Add it to `MediaService` in `providers/models.py`, plus a client in
   `providers/clients/media.py`.
2. Engine code reads the key only through `engine/integrations.py` (`require_key`, `get_key`).
   Add a setup hint there so a missing key raises `IntegrationNotConfigured` with useful
   guidance.
3. Test with `httpx.MockTransport` (see `tests/test_media_clients.py`).

**A new orchestrator tool or specialist capability**

1. Add a function to `OrchestratorTools.tools()` in `engine/orchestrator/chat.py`. Its docstring
   is the tool description; wrap the work in `self._call(...)` so it reports progress and errors.
2. Put specialist logic in `engine/orchestrator/specialists.py`; never call another specialist.
3. List the tool in `engine/orchestrator/registry.py` so the Agents page shows it.
4. Anything that spends credits must be reachable only from an explicit user request.

**A new tool endpoint**

Add a thin view in `tools/views.py` and a route in `tools/urls.py`. If it renders media or calls
a model, run it as a `GenerationJob` (see `tools/handlers.py`) and return `202`.

## Reporting security issues

See [SECURITY.md](SECURITY.md).
