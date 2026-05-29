# FrameFusion

Turn images and audio into videos. FastAPI backend + React frontend.

## Structure

```
FrameFusion/
├── api/       # FastAPI backend
└── web/       # React frontend
```

## Setup

**Backend**

```bash
cd api
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend**

```bash
cd web
npm install
npm run dev
```

- API: `http://localhost:8000` — docs at `/docs`
- Web: `http://localhost:5173`
- Requires FFmpeg on PATH

## Build list

Follow in order. Check off as you go. Full breakdown: [ROADMAP.md](./ROADMAP.md).

- [x] Monorepo layout (`api/`, `web/`)
- [x] FastAPI app structure (`core/`, `models/`, `routers/`, `services/`)
- [x] Path config + runtime dirs (`api/uploads/`, `api/output/`)
- [ ] `POST /project`
- [ ] `POST /project/{id}/media`
- [ ] `GET /project/{id}/media`
- [ ] Image-only renderer (MoviePy, no audio)
- [ ] `POST /project/{id}/render`
- [ ] `GET /job/{id}/status`
- [ ] `GET /job/{id}/download`
- [ ] Output format presets (16:9, 9:16, 1:1)
- [ ] Frontend: file upload (drag & drop)
- [ ] Frontend: media grid
- [ ] Frontend: render button + status polling
- [ ] Frontend: download link

## License

MIT — see [LICENSE](./LICENSE).
