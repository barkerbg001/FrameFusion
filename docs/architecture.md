# FrameFusion agent architecture

FrameFusion has **one orchestrator**. It is the only agent you talk to. It plans the video,
delegates each production stage to a specialist or service, checks what comes back and
assembles the final MP4. Everything runs on the local Django API; the browser never sees a key.

```text
You
 └─ Orchestrator  (personality: Director or Creative Partner)
     ├─ Research specialist   Wikipedia, weather, time, Pokemon tools → research report
     ├─ Script specialist     → script with scenes (narration, on-screen text, image query)
     ├─ Visual specialist     search_images, inspect_image_candidate, download_image,
     │                        assign_scene_image, list_project_assets → scene-to-image map + gaps
     ├─ Ideas specialist      → idea list (chat only)
     ├─ Music specialist      → standalone track (on request only)
     └─ Services (deterministic, no model)
         ├─ Narration         Edge TTS (online, free) or ElevenLabs (credits), never both
         ├─ Music bed         procedural background track
         ├─ Timeline renderer cuts scenes to narration timing, 1080×1920 MP4
         └─ Quality check     reopens the video: resolution, duration, audio, scene images
```

Specialists report only to the orchestrator. They cannot call each other or talk to you;
`specialists.delegated()` enforces a delegation depth of one.

## Personalities

`engine/orchestrator/personalities.py` defines `director` and `creative_partner`. A personality
is a short *voice* block appended **after** the operational prompt (`chat.OPERATIONAL_PROMPT`)
and the closing lines of production summaries. It never changes tools, permissions, model
routes, schemas or completion criteria; `tests/test_orchestrator.py` asserts that both
personalities get the same system prompt prefix and the same tool list.

- The default is stored on `AppSettings.orchestrator_personality` (`PUT /api/settings/personality`).
- A project can override it (`PATCH /api/projects/<id>` with `personality`, or `null` to follow
  the default).
- Each job snapshots the effective personality in `job.input["personality"]`. Switching while a
  job runs returns `personality_applies: "next_turn"`; the running job keeps its voice and the
  next message or production uses the new one.

**Personalities are not model routes.** Routes (`planner` = "Orchestrator and writing",
`production` = "Visual specialist") decide which provider and model a call uses and are set in
Settings → Models. Both personalities use the same routes.

## Chat

`chat.run_orchestrator_chat` gives the orchestrator these tools:

| Tool | What it does |
| --- | --- |
| `get_project_status` | Reads persisted tasks, the brief and project assets |
| `delegate_research` | Research specialist |
| `brainstorm_ideas` | Ideas specialist |
| `plan_video` | Runs the production up to the script (no media spend) |
| `produce_video` | Full production; only when your latest message asks for it, at most once per reply |
| `list_project_assets` | Images, audio and video with licences |

Tool calls are reported as `tool` job events (running, then ok or failed), so the workspace
shows tool activity live.

## Production run

`production.run_production` executes these stages as persisted `ProductionTask` rows:

```text
brief → research → script → visuals ─┐
                         └→ narration → music → render → qc
```

| Status | Meaning |
| --- | --- |
| `proposed` | Planned for this production, not started |
| `active` | Running now |
| `completed` | Produced an artifact, not yet checked |
| `verified` | Artifact checked (schema, files exist, scene references valid, QC passed) |
| `failed` | Attempt failed; the error is recorded on the task |
| `cancelled` | You cancelled the job during this stage |
| `skipped` | Not needed (e.g. research for a simple brief, narration for a silent short) |
| `invalidated` | An upstream artifact changed or you edited the scene images; must run again |

- **Reuse.** Each stage's inputs are hashed. A verified task with the same hash is reused
  instead of rerun, so retries and reruns only pay for what changed.
- **Invalidation.** When a stage produces a different artifact, everything downstream
  (`schemas.downstream_of`) is invalidated. Replacing or removing a scene image invalidates
  render and QC.
- **Resume, retry, rerun.** Retrying a failed or cancelled production reruns it with the same
  request; verified stages are reused, so it resumes where it stopped.
  `POST projects/<id>/production/rerun` with `from_stage` forces that stage and everything after
  it. A narration failure raises `narration_failed`; `POST jobs/<id>/retry-narration` resumes the
  production from the narration stage with the same or the other provider (your choice, never
  automatic).
- **Limits.** Each stage has `max_attempts`; the script specialist gets one revision if the
  orchestrator's script check finds problems; the visual specialist has a tool-call budget;
  one production per chat reply.
- **Honest reporting.** The final summary lists what was produced, what was reused and every
  limitation (missing Pexels, rate limits, scene gaps, placeholder scenes, QC problems). A QC
  failure fails the job with `qc_failed` instead of reporting success.

## Image tools

`engine/services/images/`:

- `safe_fetch.py` – the only way images are downloaded. http/https only, ports 80/443, no
  credentials in URLs, DNS resolved and every address checked against private, loopback,
  link-local and reserved ranges, redirects followed manually and re-checked, content-type and
  size limits, streaming with partial-file cleanup, bounded retries on transient errors.
- `sources.py` – Pexels (if configured), Openverse (anonymous; mature results filtered), a
  direct image URL, and images found on a webpage (`webpage.py`: og/twitter images, `img`
  `src`/`srcset`/`data-src`, logos and SVGs skipped).
- `candidates.py` – `ImageCandidate` with provider, title, creator, licence, licence URL,
  attribution, source page and `rights_status` (`documented` or `unknown`); Pillow validation
  (decodes the image, rejects tiny or oversized images) and a vertical-fit hint.
- `toolkit.py` – `ImageToolkit`, the visual specialist's tools: `search_images`,
  `inspect_image_candidate`, `download_image`, `assign_scene_image`, `list_project_assets`.

Rules:

- Automatic selection only downloads `documented` licences. URL and webpage images are
  `unknown` and are only downloaded when you supplied the link (in the production request or
  in the Scenes tab).
- Downloads are stored once per SHA-256 checksum (`reused_existing_file`), with all source
  metadata on the `MediaAsset` (`role="scene_image"`).
- If the visual specialist's model leaves scenes unassigned, `auto_fill` takes the top
  documented-licence result for the scene's query. Anything still missing is reported as a
  gap with a reason, and the renderer uses a title card for that scene.
- In the UI, image search is synchronous and free. Candidates are cached server-side for an
  hour, and the browser downloads by `candidate_id` only, so licence metadata can't be forged
  from the client.

## Workspace UI

- Header: personality switcher (project override) and narration chip.
- Activity tab: the orchestrator (avatar and voice of the job's personality), the specialist
  currently working, each stage with its task status, attempts, limitations and a "redo from
  here" action, tool calls, the event log and model usage.
- Scenes tab: each scene's narration, image, source, licence, attribution and rights flag,
  plus gaps. Replace (search Pexels, Openverse, a URL or a webpage), remove, and re-render.
- Failures say which stage stopped and offer resume, narration retry or the relevant
  Settings page.

## What was removed

The previous design had two named agents (Framey and Reel) plus a ten-step pipeline of
plan-only agents: director, producer/workflow, cinematography, voice, music director, sound
design and editor. Several produced plans that nothing consumed, the visual agent only planned
Pexels queries, and the render used a single background for the whole video. These were
replaced by the orchestrator, the specialists and services above, persisted tasks, real image
tools and a per-scene timeline renderer.
