# Public repository readiness: FrameFusion

Audit date: 2026-10-03/04. Repository: [barkerbg001/FrameFusion](https://github.com/barkerbg001/FrameFusion)
(already public, MIT).

## Verdict

**Not ready yet.** It becomes **ready with limitations** once owner actions 1–4 below are done.

The code in this working tree is in good shape for open-source contributions:

- no real secrets in the tree, history or local branches;
- localhost-only security model is sound and documented;
- CI is hardened, dependency audits are clean, and a fresh clone sets up and passes every check
  by following the README.

Three things keep it from being ready today:

1. **None of this work is published.** Public `main` is still at `a86a500` (2026-06-21). The
   rewrite, the new documentation, the CI hardening and the fixes in this audit exist only as
   uncommitted changes.
2. **Public history contains a commercial music track** (an MP3 by a commercial artist, added in
   `d56def1`, removed in `4e089a8`). Deleting it from the tip does not stop redistribution;
   anyone can still download it from history.
3. **Private vulnerability reporting appears to be off.** The public Security page shows no
   "Report a vulnerability" option, so `SECURITY.md` falls back to "open a minimal issue".

## Scope and method

| Area | What was checked | Commands / tools |
| --- | --- | --- |
| Secrets | Working tree, all 47 commits, the local branch, 8 fetched remote dependabot branches, the stash, 0 tags | Gitleaks 8.30.1 `git . --log-opts=--all --redact`; `dir . --redact` (includes ignored files); `git log --all -- <path>` for env/DB files; manual review of hits |
| Private data | Commit metadata, history for runtime files (DB, `.env`, media) | `git log --all --format=…`, `git rev-list --objects --all` + `cat-file` for large blobs |
| App security | Request guard, CSRF, settings, media serving, uploads, SSRF fetcher, subprocess calls, redaction, orchestrator tools, Pillow decoding | Code review of `common/`, `config/settings.py`, `studio/`, `tools/`, `engine/services/`, `providers/clients/base.py`, `engine/orchestrator/chat.py` |
| Dependencies | Python and both npm trees | `pip-audit -r api/requirements.txt`, `npm audit` (root and `web/`) |
| Licensing | Licence file, bundled npm packages, Python runtime dependencies, repository assets, external services | Package metadata, asset inventory (`git ls-files`, untracked assets) |
| CI | Workflow permissions, triggers, secret exposure, pinned tools | Review of `.github/workflows/ci.yml` |
| Fresh clone | Isolated copy in a temp directory with a space in its path; separate ports 8010/5180 | `npm install`, `npm run setup`, `npm run dev:api`, Vite, `npm run ci`, `npm run typecheck:web`, browser walk-through |

The owner's database, `api/.env`, uploads and generated media were not read, copied or changed.
Gitleaks scanned `api/.env` as part of the directory scan, but only the rule name and file path
were reported, never the values.

## Findings by severity

### High

**H1. Commercial music track in public history.**
- What: `audio/<artist> - <track>.mp3` (about 2.7 MB), added in `d56def1` (2023-04-05) and
  removed in `4e089a8` (2023-04-23). It is still reachable from public history.
- Status: **owner action** (history rewrite; not done, as it needs authorisation).

**H2. Reviewed code and documentation are not published.**
- What: public `main` (`a86a500`) still has the old README, no SECURITY/CONTRIBUTING/CODE_OF_CONDUCT,
  and the old CI.
- Status: **owner action** (review and commit).

### Medium

**M1. Private vulnerability reporting not enabled.**
- What: based on the public Security page.
- Status: **owner action**.

**M2. Pillow advisories that cannot be fixed by upgrading.**
- What: 18 2026 Pillow advisories are fixed only in Pillow 12, and MoviePy 2.2.1 requires
  `pillow<12`.
- Status: **mitigated**. Decoding is restricted to JPEG/PNG/WebP, with a regression test. The
  advisories are documented in `api/pip-audit-ignore.txt` and `SECURITY.md`.

**M3. Windows helper scripts passed arguments through `cmd.exe` (`shell: true`).**
- What: this broke paths with spaces and let shell metacharacters in arguments be interpreted.
- Status: **fixed** in `scripts/run-api.mjs`, `run-api-tool.mjs` and `setup-api.mjs`; spawn
  errors are now reported.

**M4. Vulnerable npm dev/runtime packages.**
- What: `concurrently` (dev tooling) and `dompurify` (sanitises rendered Markdown).
- Status: **fixed**. Upgraded to `^10.0.5` and `^3.4.16`, and the lockfiles were refreshed. Both
  trees now report 0 vulnerabilities.

**M5. AI-generated and project-made assets have no recorded provenance.**
- What: agent avatars and illustrations (WebP), plus the logo, wordmarks and app icons.
- Status: **partly fixed**. Provenance is recorded in `THIRD_PARTY_NOTICES.md` as stated by the
  owner, with a caveat. The owner should confirm the image generator's terms.

### Low

**L1. `produce_video` (paid work) is gated by the model prompt.**
- What: there is no server-side confirmation step. Mitigations: it runs only within a chat turn
  the user started, at most once per reply, and defaults to free Edge narration.
- Status: **accepted for now**. A UI confirmation is recommended.

**L2. The Vite proxy ignored `FRAMEFUSION_HOST`/`FRAMEFUSION_PORT`.**
- What: with a moved API, the web app called the wrong port.
- Status: **fixed** in `web/vite.config.ts` and documented in the README.

**L3. Old unknown-origin binaries in history.**
- What: `project.avi`, `images/test/dgg.png`, `ui/icon/*.ico`, and `ui/resource_rc.py` (an
  embedded icon resource).
- Status: **owner action**. Include them in the rewrite if their source is unknown.

**L4. Commit metadata exposes two personal and work email addresses.**
- Status: **owner action** (optional). Use a GitHub noreply address from now on; rewriting
  authors is optional.

**L5. Stale GitHub repository description.**
- What: it still mentions FastAPI and an old agent name.
- Status: **owner action**.

**L6. Gitleaks flags dummy test keys.**
- What: the matches are in `api/tests/test_provider_settings.py`, `test_orchestrator.py` and
  `test_studio.py`.
- Status: **fixed**. They are marked `# gitleaks:allow (dummy)`; the values are obviously fake.

**L7. A new contributor can't get past the setup guide without saving an AI provider key.**
- What: the UI shows a clear message: "Save a key for at least one AI provider to continue."
- Status: **documented** in CONTRIBUTING ("Working without paid keys"). The product behaviour is
  unchanged.

**L8. Local `api/.env` still holds provider keys from the old env-var setup.**
- What: 7 key-shaped values (Gitleaks rules `gcp-api-key` and `generic-api-key`). The file is
  git-ignored and has **never been committed** (0 commits touch it).
- Status: **owner action**. Run `npm run manage -- import_env_keys`, then delete those lines.

No credential was found in any commit, so **no credential is considered compromised** by this
audit.

## Fixes made in this audit

**Secrets**
- Added Gitleaks to CI (full history, pinned to v8.30.1 with checksum verification).
- Added `.pre-commit-config.yaml` with an optional Gitleaks hook.
- Added `.gitignore` rules for key and certificate files and Gitleaks reports.
- Added `.gitattributes`.

**Application security**
- Restricted Pillow decoding to JPEG/PNG/WebP
  (`engine/services/images/candidates.py`, `engine/services/text_video_creator.py`).
- Added a regression test: `tests/test_images.py::test_renderer_only_decodes_jpeg_png_and_webp`.
- Removed `shell: true` from the Node helper scripts.

**Dependencies**
- Upgraded `concurrently` and `dompurify`.
- Documented the Pillow constraint in `api/requirements.txt`, `api/pip-audit-ignore.txt` and
  `SECURITY.md`.

**CI**
- Rewrote `.github/workflows/ci.yml`:
  - least-privilege `contents: read` and `persist-credentials: false`;
  - only `push`, `pull_request` and scheduled runs, with no `pull_request_target`, so forks get no
    secrets;
  - separate web, api, secrets and audit jobs.
- Added `.github/dependabot.yml` (npm ×2, pip, actions; grouped).

**Contributor experience**
- Added `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).
- Added issue forms and a PR template; the issue config links to private advisories.
- Updated `CONTRIBUTING.md`:
  - platforms;
  - working without paid keys;
  - sample data and secrets;
  - CI and pre-commit;
  - agent rules;
  - how to add a provider, media integration, orchestrator tool or endpoint.
- Updated `README.md` (platforms, prerequisites, what needs a key, proxy port, licence notes) and
  `SECURITY.md` (supported version, known advisories).

**Licensing**
- Added `THIRD_PARTY_NOTICES.md` covering:
  - bundled npm packages;
  - notable Python dependencies (edge-tts LGPL-3.0, FFmpeg builds, certifi MPL-2.0);
  - asset provenance;
  - external service terms.

**Fresh clone**
- Fixed the proxy port mismatch (L2).

## Secret scan coverage and limits

| Covered | Result |
| --- | --- |
| All 47 commits reachable from local refs (`--all`: `main`, `origin/*` including 8 dependabot branches, stash) | No findings |
| Working tree (tracked + untracked publishable files) | Only marked dummy test keys |
| Ignored local files (`api/.venv`, `api/.mypy_cache`, `api/.env`) | 56 hits, all in ignored files: vendored test fixtures in packages, cache, and the owner's local `.env` (L8). None tracked |
| `.env`, database and `api/var/` in history | Never committed |
| Large or binary blobs in history | Reviewed; see H1 and L3 |

**Not covered:**
- GitHub pull-request refs and forks;
- issues, discussions and wiki;
- GitHub Actions logs and artefacts;
- releases.

The `gh` CLI was not available. Gitleaks finds known key formats and high-entropy strings; it
can miss custom formats.

## Licensing status

**Project code.** MIT (`LICENSE`, © 2023 barkerbg001). No licence was changed or added.

**Bundled frontend.**
- lucide: ISC, with MIT for icons derived from Feather.
- DOMPurify: MPL-2.0 or Apache-2.0.
- marked: MIT.

All are compatible with MIT redistribution when their notices are kept. They are listed in
`THIRD_PARTY_NOTICES.md`.

**Python runtime.** Dependencies are installed by users, not vendored.
- edge-tts is LGPL-3.0. That's fine as an unmodified dependency.
- MoviePy and imageio-ffmpeg download FFmpeg builds that can be GPL; they aren't redistributed.
- certifi is MPL-2.0.

**Repository assets.**
- SVG logo, wordmarks and app icons: made for the project.
- Avatars and illustrations: AI-generated, per the owner. Generated images don't automatically
  come with unrestricted rights, so the owner should confirm the generator's terms (owner
  action 5).
- No fonts, audio or voice models are bundled.

**Output media.** Narration (Microsoft Edge speech service, ElevenLabs), stock media (Pexels,
Openverse), Wikipedia text and Open-Meteo data have their own terms. The README and notices say
so and make no commercial-use promises.

**Historical media.** The commercial MP3 (H1) is not licensed for redistribution. Other old
binaries (L3) have unknown origins.

## Fresh-clone and CI results

The fresh clone was made in a temp directory whose path contains a space, using Python 3.13 and
Node 22 on Windows.

| Step (as documented in README) | Result |
| --- | --- |
| `npm install` | OK |
| `npm run setup` | OK: created `api/.env` with generated secrets, applied 7 migrations |
| `npm run dev:api` (port 8010 via `FRAMEFUSION_PORT`) + Vite on 5180 | Started; `GET /api/app` through the Vite proxy returned 200 |
| Browser: setup guide | Welcome renders with both personalities and explains Edge TTS is online. Without a key, the AI provider step blocks with a clear message (L7) |
| `npm run ci` | Passed: web build, ruff check, ruff format check, mypy (no issues in 72 files), `makemigrations --check`, 137 tests |
| `npm run typecheck:web` | Passed |

These checks were also run in the main working tree:

| Check | Result |
| --- | --- |
| `npm run ci` and `npm run typecheck:web` | Passed (137 tests) |
| `npm audit` (root and `web/`) | 0 vulnerabilities |
| `pip-audit` | No known vulnerabilities beyond the documented Pillow exceptions |
| Gitleaks history scan | No leaks |

The GitHub Actions workflow itself has not run yet, because it isn't committed. The first run
after committing will confirm the Linux jobs.

## Owner actions

1. **Review and commit** the working tree, then push to `main`. A plain `git add -A` is safe:
   runtime files are ignored.
2. **Decide on a history rewrite** to remove the commercial MP3 (and optionally the L3
   binaries). Doing this rewrites shared history and needs a force-push; this audit didn't do it.
   - Make a backup mirror.
   - Run `git filter-repo --invert-paths --path "audio/" --path project.avi --path images/test/ --path ui/`.
   - Force-push all branches.
   - Ask GitHub Support to purge cached views and pull-request refs.
   - Tell anyone with a clone to re-clone.
3. **Enable private vulnerability reporting**: repository Settings → Code security → Private
   vulnerability reporting.
4. **Update the repository description and topics** on GitHub so they match the README.
5. **Confirm the terms** of the image generator used for the avatars and illustrations. Adjust
   `THIRD_PARTY_NOTICES.md` if they differ.
6. **Move legacy keys out of `api/.env`**: run `npm run manage -- import_env_keys`, then delete
   those lines. Rotate any key you have ever shared or pasted elsewhere.
7. Optional:
   - add a UI confirmation before full production (L1);
   - use a GitHub noreply commit email (L4);
   - rebuild `api/.venv` from `requirements-dev.txt` to drop unused leftover packages.
