# Deployment

FrameFusion ships as two Docker containers: **api** (FastAPI + FFmpeg) and **web** (nginx serving the React app and proxying `/api`).

## Docker Compose (recommended)

From the repository root:

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Web UI | http://localhost:8080 |
| API (direct) | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

Uploads and rendered videos persist in Docker volumes (`api-uploads`, `api-output`).

Stop the stack:

```bash
docker compose down
```

Remove volumes as well:

```bash
docker compose down -v
```

## Environment variables

### API (`api/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `UPLOADS_DIR` | `./uploads` | Upload storage path |
| `OUTPUT_DIR` | `./output` | Rendered video output path |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |

Copy `api/.env.example` to `api/.env` for local development.

### Web (build-time)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | empty | API origin for production builds. Leave empty when nginx proxies `/api` on the same host. |

## Production checklist

1. Set `CORS_ORIGINS` to your public web origin only.
2. Put TLS in front of the web container (Caddy, nginx, or a cloud load balancer).
3. Increase proxy timeouts for long video renders (the included `web/nginx.conf` sets 3600s).
4. Plan disk space for `uploads` and `output` volumes.
5. Add authentication before exposing publicly (see ROADMAP Phase 5).

## Cloud deployment options

Any platform that runs Docker works. Common choices:

### VPS + Docker Compose

1. Install Docker on the server.
2. Clone the repo and run `docker compose up -d --build`.
3. Point a domain at the server and terminate TLS with Caddy or nginx.

### Railway / Fly.io / Render

1. Build and deploy the `api` and `web` Dockerfiles as separate services.
2. Set `VITE_API_URL` at **web build time** to the public API URL if they are on different hosts.
3. Mount persistent storage for `UPLOADS_DIR` and `OUTPUT_DIR` on the API service.
4. Configure health checks against `/health`.

### Split build example (web)

```bash
docker build \
  --build-arg VITE_API_URL=https://api.yourdomain.com \
  -t framefusion-web \
  ./web
```

## CI

GitHub Actions runs on every push and pull request to `main`:

- API: Ruff, Mypy, pytest (with FFmpeg)
- Web: ESLint, Vitest, production build
- Docker: image builds on pushes to `main`

See [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## Local development vs production

| | Development | Docker Compose |
|--|-------------|----------------|
| Web | `npm run dev` on :5173 | nginx on :8080 |
| API | `uvicorn` on :8000 | uvicorn on :8000 |
| API proxy | Vite dev proxy | nginx `location /api/` |
