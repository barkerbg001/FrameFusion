# Third-party notices and asset sources

FrameFusion's own code is released under the [MIT License](LICENSE). This file records where
bundled assets come from and which third-party licences apply to code that ships with the web
app or is installed as a dependency. Add an entry here whenever you add a bundled asset.

## Bundled assets

| Files | Source | Terms |
| --- | --- | --- |
| `web/public/favicon.svg`, `web/public/brand/wordmark-*.svg`, `web/public/site.webmanifest` | Made for this project (simple geometric "F" mark and text). The wordmark names the Inter font but does not embed it; it renders with whatever font the viewer has. | MIT, as part of FrameFusion |
| `web/src/assets/agents/*.webp` (orchestrator personality avatars) | Generated for this project with an AI image tool (Cursor image generation), then cropped and converted to WebP. No third-party artwork was used as input. | Released with FrameFusion under MIT to the extent the maintainer holds rights. AI-generated images may not be protected by copyright in every jurisdiction. |
| `web/src/assets/illustrations/*.webp` (onboarding and empty states) | Generated the same way as the avatars. | As above |

No fonts, audio, video, voice models or example media are bundled. The video renderer uses
fonts already installed on your system (Arial or DejaVu Sans). Narration, images and music are
produced or downloaded at run time and stored in git-ignored folders.

## Code bundled into the web app

These npm packages are compiled into `web/dist` by `npm run build`. Keep their notices with any
build you distribute.

| Package | Licence |
| --- | --- |
| [lucide](https://github.com/lucide-icons/lucide) (icons) | ISC, © Lucide Icons and Contributors; icons derived from [Feather](https://github.com/feathericons/feather) are MIT, © 2013-present Cole Bemis |
| [DOMPurify](https://github.com/cure53/DOMPurify) | MPL-2.0 or Apache-2.0 |
| [marked](https://github.com/markedjs/marked) | MIT |

## Python dependencies

Python packages are installed from PyPI by `npm run setup` (`api/requirements*.txt`); none are
vendored in this repository. Licences worth knowing about:

- `edge-tts`: LGPL-3.0. Used as an unmodified, separately installed library.
- `imageio-ffmpeg` (pulled in by MoviePy) and `opencv-python-headless` ship or download FFmpeg
  binaries, which are LGPL or GPL depending on the build. FrameFusion runs FFmpeg as a separate
  program and does not redistribute it.
- `certifi`: MPL-2.0.
- Everything else in the dependency tree is under permissive licences (MIT, BSD, Apache-2.0,
  PSF, ISC or similar).

## External services

FrameFusion calls these services only when you use the matching feature. Their terms apply to
you, not just to the code:

| Service | Used for | Notes |
| --- | --- | --- |
| OpenRouter, Google Gemini, Anthropic | AI models | Your own key and account terms |
| ElevenLabs | Optional narration and music | Your own key; output rights follow your ElevenLabs plan |
| Microsoft Edge read-aloud (via `edge-tts`) | Free narration | Unofficial, undocumented service; no promise of availability or commercial rights |
| Pexels | Stock photos and videos | [Pexels licence](https://www.pexels.com/license/); API terms require crediting Pexels and photographers where possible |
| Openverse | Creative Commons images | Each image keeps its own licence and attribution, recorded on the media asset |
| Open-Meteo | Weather lookups | Free API is for non-commercial use; data is CC BY 4.0 |
| Wikipedia | Research lookups | Text is CC BY-SA 4.0; credit Wikipedia if you reuse wording |
| PokéAPI | Pokémon lookups | Free API with a fair-use policy |

Licence information for downloaded images comes from the source and is not verified by
FrameFusion. Check it before publishing a video.
