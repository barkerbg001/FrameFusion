# Security

## Reporting a vulnerability

This repository does not have a dedicated security contact. Please don't put exploit details
in a public issue. Instead, use GitHub's private vulnerability reporting (the **Security** tab →
**Report a vulnerability**) if the maintainers have enabled it for
[barkerbg001/FrameFusion](https://github.com/barkerbg001/FrameFusion). If it is not enabled,
open a minimal public issue asking a maintainer to get in touch, without technical details.

There is no formal support policy or response-time commitment. Only the latest `main` branch is
maintained.

## Known dependency advisories

MoviePy 2.2 requires Pillow below 12, so FrameFusion cannot yet install the Pillow releases that
fix several 2026 advisories. To limit exposure, FrameFusion only decodes JPEG, PNG and WebP with
Pillow, and every downloaded image passes size and type checks first. The ignored advisory IDs
and the reason for each are in `api/pip-audit-ignore.txt`. They will be removed when MoviePy
allows a fixed Pillow.

## Deployment model: one person, one machine

FrameFusion is a **single-user application without login**. Every request that reaches the
API acts as the owner: it can read projects, start paid generation with your saved provider
keys, and change or remove those keys. That is safe only when the API can be reached from
nowhere but your own computer.

**Do not host FrameFusion on a public server, a shared network, or behind a port forward.**

Defaults that enforce this:

- `npm run dev:api` binds to `127.0.0.1`. `scripts/run-api.mjs` refuses a non-loopback
  `FRAMEFUSION_HOST` unless `FRAMEFUSION_ALLOW_REMOTE` is set.
- `DJANGO_ALLOWED_HOSTS` defaults to localhost names. This also defeats DNS-rebinding attacks
  from web pages you visit.
- `FRAMEFUSION_FRONTEND_ORIGINS` defaults to the local Vite origins. Django refuses to start
  when a non-local host or origin is configured without `FRAMEFUSION_ALLOW_REMOTE=true`.
- A middleware rejects API requests that the browser marks as cross-site
  (`Sec-Fetch-Site: cross-site`), unsafe requests whose `Origin` is not an allowed frontend, and
  unsafe requests with `Origin: null`, such as sandboxed or `file://` pages.
- Every unsafe request must carry Django's CSRF token. Responses send `X-Frame-Options: DENY`,
  `nosniff`, and same-origin referrer and opener policies.

`FRAMEFUSION_ALLOW_REMOTE=true` removes the start-up guard; it does not add authentication. Only
set it if something in front of FrameFusion already restricts access to you, such as a VPN or a
reverse proxy with its own login. Serve over HTTPS and set `DJANGO_SECURE_COOKIES=true` in that
case. You are responsible for that layer.

## API keys

- Keys for OpenRouter, Gemini, Anthropic, ElevenLabs and Pexels are entered in the app and sent
  only to the local API. They are encrypted with Fernet (`cryptography`) before they are written
  to SQLite, using `FRAMEFUSION_ENCRYPTION_KEY` from `api/.env`.
- The encryption key lives outside the database. Without it, the app refuses to save keys and
  shows a banner. Back it up separately from database backups; if it is lost, saved keys must
  be re-entered. To rotate it, put a new key first in the comma-separated list, re-save keys,
  then remove the old one.
- The API never returns a key. The browser only sees masked values (`••••abcd`). Keys are
  never written to browser storage, URLs, logs, job events or error messages; provider errors
  are passed through a redaction filter.
- All provider calls are made by the server. There is no global or shared credential, and keys
  are not read from environment variables at runtime (`import_env_keys` is a one-time
  migration).

## Paid actions

Generation never starts on its own. Chat replies, productions, renders, narration previews and
narration retries run only after an explicit click. Connection tests use free endpoints where
providers offer them, and each card says what its test costs. FrameFusion never switches from
free Edge TTS narration to ElevenLabs (or back) on its own.

## Data sent to third parties

AI prompts go to the AI provider you selected. Narration text goes to the narration provider you
selected: with **free Edge TTS** (the default) the server sends it, without any key, to
Microsoft's online speech service through the unofficial `edge-tts` client; with ElevenLabs it
goes to ElevenLabs using your key. Stock searches go to Pexels. Choose ElevenLabs or avoid
narration if your script must not reach Microsoft.

## Files that must stay private

`api/.env`, the SQLite database in `api/var/` (including `*.accounts-backup-*` files from the
upgrade), `api/var/uploads/` and `api/generated/` are git-ignored. Do not commit or share them.
