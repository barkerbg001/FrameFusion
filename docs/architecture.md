# FrameFusion agent architecture

FrameFusion has **one orchestrator**. It is the only agent you talk to. It plans the video,
delegates each production stage to a specialist or service, checks what comes back and
assembles the final MP4. Everything runs on the local Django API; the browser never sees a key.

```text
You
 └─ Orchestrator  (personality: Director or Creative Partner)
     ├─ Research specialist   Wikipedia, weather, time, Pokemon tools → research report
     ├─ Script specialist     → script with scenes (narration, on-screen text, image query)
     ├─ Visual specialist     build_visual_brief, search_image_sources, inspect_image_candidates,
     │                        rank_image_candidates, download_and_register_image,
     │                        list_project_assets, report_visual_gap
     │                        → per-scene briefs, chosen images, assessed alternatives and gaps
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
  limitation (missing sources, rate limits, unresolved scenes, title cards, QC problems). A QC
  failure fails the job with `qc_failed` instead of reporting success.

## Scene images

The goal is an image that shows what the scene is about, or an honest gap. A search that
returns *something*, or a download that succeeds, is never treated as proof of relevance.

### Pipeline

```text
visual brief → search (bounded, subject-preserving queries) → filter (licence, size, format,
duplicates) → inspect previews (vision model, titles withheld) → decide and rank →
download + validate → register MediaAsset (+ render variant) → scene state
```

Each scene ends in one persisted state (`job.output.visuals.scenes[n]` and the scene map):
`searching`, `candidates_found`, `awaiting_review`, `selected`, `no_suitable_result` or
`download_failed`, together with its brief, the assessed alternatives (up to six), the queries
that were tried and the next actions offered.

### Visual brief (`brief.py`)

`VisualBrief` per scene: purpose, subject, action, named entities (person, place, landmark,
product, organisation, artwork, species, event), specificity (`exact`, `representative`,
`generic`), visual type (photograph, illustration, diagram, map, screenshot), orientation and
minimum short side, composition, acceptable alternatives, exclusions and up to four queries,
each with a rationale. The visual specialist writes it with `build_visual_brief`; if the model
call fails, `derive_brief` builds a conservative one from the script (named subjects make it
`exact`).

`query_problem` rejects queries that lose the subject: for exact subjects every query keeps
the full name; otherwise every query keeps at least one subject term. Queries are never
broadened into generic words, and `refine_brief` refuses a new subject that drops the old one.

### Sources (`sources.py`)

| Source | Key | Rights | Notes |
| --- | --- | --- | --- |
| Pexels | Optional | Documented (Pexels License) | Photographer credit kept |
| Pixabay | Optional | Documented (Pixabay Content License) | Photos, illustrations, vectors; results cached 24 h as required |
| Wikimedia Commons | None | Documented per file (`extmetadata`) | Only CC0, public domain, CC BY and CC BY-SA; NC, ND and non-free files are dropped. Identifying User-Agent |
| Openverse | None | Documented (CC licences) | `by,by-sa,cc0,pdm` only, mature results filtered |
| Brave image search | Optional, paid | **Unknown** | Discovery only, see below |
| Image URL / webpage | None | Unknown | Only when you supply the link (`webpage.py`: og/twitter images, `img` sources) |
| Pasted link (`link`) | None | Unknown | A Google Images result, page or image link you paste (`pasted.py`); user-facing search only |
| Upload | None | Unknown | Validated like any download |

`plan_sources` picks the order from the brief: exact subjects try Wikimedia and Openverse
before Pexels; illustrations and diagrams try Wikimedia and Pixabay; generic subjects start
with stock. Sources that are not set up are listed as limitations.

**Brave** is a documented, paid API used for discovery only: at most one search per scene,
only after the licensed sources found nothing suitable, the key only in the request header,
and every result is `rights_status="unknown"`. The specialist cannot download a Brave result;
it is offered to you as an alternative to review. No source is scraped and no undocumented
endpoint is used.

**Google Images (assisted, never automated).** Google's terms forbid automated access that
ignores its robots.txt (`Disallow: /search`, `/imgres`), and the Custom Search JSON API is
closed to new customers and ends on January 1, 2027. So there is no Google client, scraper or
browser automation. Instead:

- The Scenes tab links to `https://www.google.com/search?udm=2&q=<brief query>`, which opens
  in your own browser.
- You paste a result. `pasted.parse_link` reads it locally: `/imgres` gives `imgurl` (image),
  `imgrefurl` (publisher page) and `w`/`h`; `/url` gives `q`/`url`. Google results pages,
  `gstatic` thumbnails (`tbn`) and `data:` URIs are refused with instructions
  (`google_page`, `preview_only`), because a thumbnail is not a production-quality original.
  Anything that would point back at Google is refused too, so no request is ever sent to it.
- `pasted.resolve` checks the image URL, then reads the publisher page through `safe_fetch`
  (HTML only, 3 MB cap, no cookies or credentials). `webpage.parse_page` finds the image on
  the page (`same_image`: host and path, ignoring resize queries) and the rights the page
  states: JSON-LD `ImageObject` `license`, `acquireLicensePage`, `creditText`, `creator` and
  `copyrightNotice`; `rel=license`; and `author`, `copyright`, `dcterms.rights` and
  `og:site_name` meta tags. Creative Commons URLs are labelled (`license_label`).
- Candidates are `provider="webpage"`, `user_supplied=True` and `rights_status="unknown"`,
  with `discovered_via="google_images"`, `publisher` and `found_on_page`. The licence reads
  "CC BY 4.0 (stated by publisher)" and is not treated as documented. These fields are stored
  in `MediaAsset.metadata` on download.
- When the publisher page can't be read, the image is still offered, with a note and unknown
  rights. A link with no usable image returns no candidates ("No suitable image found").
- The `link` source exists only in the user-facing search (`studio/images.py`). It is not in
  `SEARCH_SOURCES`, so the specialist can't use it.

`POST projects/<id>/images/search` with `scene_index` adds a free metadata `decide()` to each
result. `POST projects/<id>/images/check` copies up to six cached candidates into an
`image_check` `GenerationJob` (202). The job runs `VisionJudge("visual", max_calls=1)` and
returns assessments. It never runs automatically.

### Assessment (`relevance.py`)

`VisionJudge` sends up to six preview images per call to the *Visual specialist* model route
(`ImagePart`s through the normal provider clients) with the brief but **without titles or
tags**, and asks for what is visible, subject match, scene relevance, identity (for named
subjects), composition, quality, excluded content and watermarks. If the selected model can't
take images (`unsupported`, `bad_request`, `model_unavailable`) the judge switches off for the
rest of the job and the limitation is recorded; FrameFusion never switches model to get vision.

`decide` turns that into `accept`, `review`, `illustrative` or `reject`, always with reasons:

- Rejected: wrong subject, excluded content, irrelevant to the narration, a different
  landmark or person than the one named, poor quality, too small or an unsupported format.
- Exact subjects are accepted only when the image looks like the named subject **and** the
  source metadata names it. A look-alike becomes `illustrative` (only usable labelled as such).
- Watermarks, weak vertical composition, low resolution or unknown rights mean `review`.
- Without vision, candidates are marked *visually unverified*. Generic subjects need at least
  two subject terms in the metadata (a single shared word like "interior" is rejected); exact
  subjects are never accepted automatically and go to review.

The 0–100 score is a ranking heuristic, not a probability. Ranking orders by decision,
specificity fit, score and resolution.

### Download and storage (`safe_fetch.py`, `candidates.py`, `variants.py`)

- `safe_fetch.py` is the only way images are downloaded: http/https on ports 80/443, no
  credentials in URLs, every resolved address and every redirect checked against private,
  loopback, link-local and reserved ranges, content-type and byte limits (15 MB images, 4 MB
  previews), timeouts, streaming with partial-file cleanup and bounded retries.
- `validate_image` decodes with Pillow, checks the real format (JPEG, PNG, WebP), dimensions
  and pixel count, and rejects corrupt files (`download_failed` for that scene, never a
  substitute).
- Exact duplicates are found by SHA-256 and near duplicates by a 64-bit difference hash
  (≤ 6 bits apart); a duplicate is not used for a second scene.
- Files go to the managed media directory with a sanitised name. The original is kept; when a
  cover crop would keep less than 60 % of the image, `render_variant` writes a separate
  `<name>.render.jpg` (blurred fill, whole image visible), so nothing is stretched and the
  subject isn't cut off.
- Provider, creator, licence, licence URL, attribution, source page, checksum, dHash, the
  brief summary, the assessment and `selected_by` (`agent` or `user`) are stored on the
  `MediaAsset` (`role="scene_image"`).

### Visual specialist tools (`toolkit.py`)

| Tool | What it does |
| --- | --- |
| `build_visual_brief` | Validates and stores a scene's brief (or refines it without dropping the subject) |
| `search_image_sources` | Runs one brief query on one source or the planned sources; max five searches per scene |
| `inspect_image_candidates` | Vision assessment of up to six candidates at a time, twelve per scene |
| `rank_image_candidates` | Orders assessed candidates and says which, if any, may be downloaded |
| `download_and_register_image` | Downloads an `accept`ed, documented-rights candidate by id, validates and registers it; three attempts per scene |
| `list_project_assets` | Existing project images with provenance, to reuse instead of re-downloading |
| `report_visual_gap` | Records that no suitable image exists and what would fix it |

Tools return structured JSON and never raise into the model loop. Anything the specialist
leaves undecided is assessed by the same rules afterwards; a scene with no accepted image stays
`no_suitable_result` and keeps its alternatives. There is no "take the first result" fallback.

### Fallbacks

When a scene is unresolved, the Scenes tab offers: search again (another source or a refined
query), paste a Google Images result, image URL or webpage, upload a file, use a labelled illustrative alternative,
or use a title card. Nothing is substituted silently. FrameFusion has no image-generation
integration, so generating an image is not offered.

### Rights and rendering

The renderer only uses an image when its licence is documented, you supplied it (URL, webpage
or upload), or you chose it in the Scenes tab. Images with unknown rights that the specialist
proposed wait for your approval; until then the scene renders as a title card. Changing one
scene's image invalidates only render and QC, and the UI refreshes only that scene.

Image search in the UI is synchronous and free (except Brave, which uses your credits).
Candidates are cached server-side for an hour, and the browser downloads by `candidate_id`
only, so licence metadata can't be forged from the client.

## Workspace UI

- Header: personality switcher (project override) and narration chip.
- Activity tab: the orchestrator (avatar and voice of the job's personality), the specialist
  currently working, each stage with its task status, attempts, limitations and a "redo from
  here" action, tool calls, the event log and model usage.
- Scenes tab: per scene, its status, visual brief, selected image, why it was chosen, how it
  was verified (vision or metadata only), source, licence, attribution and rights, plus the
  assessed alternatives and the queries tried. Actions: search again (any source), paste a URL,
  upload, use a title card, approve an unknown-rights image, remove, and re-render.
- Failures say which stage stopped and offer resume, narration retry or the relevant
  Settings page.

## What was removed

The previous design had two named agents (Framey and Reel) plus a ten-step pipeline of
plan-only agents: director, producer/workflow, cinematography, voice, music director, sound
design and editor. Several produced plans that nothing consumed, the visual agent only planned
Pexels queries, and the render used a single background for the whole video. These were
replaced by the orchestrator, the specialists and services above, persisted tasks, real image
tools and a per-scene timeline renderer.
